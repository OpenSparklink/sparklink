//! Bounded daemon-directory observations. These are not Native events, Ready,
//! physical Down, authorization, or a receipt that resource retirement drained.
use crate::ControllerId;

pub const METHOD: &str = "GetControllerChanges";
pub const VERSION: u16 = 1;
pub const CAPACITY: usize = 64;
pub const PUBLISHED: u8 = 1;
pub const WITHDRAWN: u8 = 2;
/// Local sequence, controller index, generation, directory action.
pub type Row = (u64, u16, u64, u8);
/// Version, oldest retained sequence (zero when empty), tail, gap, rows.
pub type Batch = (u16, u64, u64, bool, Vec<Row>);

/// Validate the complete snapshot before a caller changes its cursor. No
/// permissive truncation, partial application, wrap, or implicit resynchronizing.
pub fn valid(after: u64, batch: &Batch) -> bool {
    let (version, oldest, tail, gap, rows) = batch;
    if *version != VERSION || after > *tail || rows.len() > CAPACITY {
        return false;
    }
    if *tail == 0 {
        return *oldest == 0 && after == 0 && !gap && rows.is_empty();
    }
    if *oldest == 0 || oldest > tail || tail - oldest >= CAPACITY as u64 {
        return false;
    }
    let missing = after < oldest - 1;
    if *gap != missing {
        return false;
    }
    if missing {
        return rows.is_empty();
    }
    if tail - after != rows.len() as u64 {
        return false;
    }
    rows.iter().enumerate().all(|(offset, row)| {
        after.checked_add(offset as u64 + 1) == Some(row.0)
            && row.2 != 0
            && matches!(row.3, PUBLISHED | WITHDRAWN)
    })
}

pub fn identity(row: Row) -> ControllerId {
    ControllerId {
        index: row.1,
        generation: row.2,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_shape_and_complete_contiguous_batches() {
        use zvariant::Type;
        assert_eq!(Batch::SIGNATURE.to_string(), "(qttba(tqty))");
        let batch = (1, 1, 2, false, vec![(1, 2, 7, 1), (2, 2, 7, 2)]);
        assert!(valid(0, &batch));
        for index in 0..6 {
            let mut bad = batch.clone();
            match index {
                0 => bad.0 = 2,
                1 => bad.1 = 0,
                2 => bad.2 = 3,
                3 => bad.3 = true,
                4 => bad.4[1].0 = 1,
                _ => bad.4[0].2 = 0,
            }
            assert!(!valid(0, &bad), "{index}");
        }
        assert!(!valid(3, &batch));
        assert!(!valid(0, &(1, 1, 1, false, vec![(1, 0, 1, 3)])));
    }

    #[test]
    fn gaps_and_maximum_sequence_do_not_wrap() {
        assert!(valid(0, &(1, 2, 65, true, vec![])));
        assert!(!valid(0, &(1, 2, 65, false, vec![])));
        assert!(!valid(1, &(1, 2, 65, true, vec![])));
        assert!(valid(
            u64::MAX,
            &(1, u64::MAX - 63, u64::MAX, false, vec![])
        ));
        assert!(!valid(0, &(1, 1, 65, true, vec![])));
        assert!(valid(0, &(1, 0, 0, false, vec![])));
    }
}
