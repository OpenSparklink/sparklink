//! Bounded single-value SSAP fragmentation (2025 §7.4.2), not DLI PB.
//! The caller supplies negotiated sequence support, receipt identity and the
//! original absolute deadline. No clock, socket, authorization or database.
//! The local logical budget is a 2042-byte value plus WRITE_REQ overhead.

pub const LOGICAL_MTU: u16 = 2047;
pub const MAX_PARTS: usize = 15;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Error {
    Length,
    Unsupported,
    Mtu,
    Capacity,
    Sequence,
    Interleaved,
    Identity,
    Expired,
    Control,
    Output,
}

fn supported(op: u8) -> bool {
    matches!(op, 8 | 9 | 11 | 13 | 14)
}

/// Requests and responses have independent ordered flow-control spaces.
pub fn lane(opcode: u8) -> Option<usize> {
    match opcode & 0x7f {
        8 | 13 => Some(0),
        9 | 11 | 14 => Some(1),
        _ => None,
    }
}

/// True only for the supported value opcodes; the low bits of e.g. UUID_REQ
/// are not fragmentation flags. Extended complete value PDUs also normalize.
pub fn needs_reassembly(raw: &[u8]) -> bool {
    raw.len() >= 2 && supported(raw[0] & 0x7f) && (raw[0] & 0x80 != 0 || raw[1] & 3 != 3)
}

/// The actual immutable byte layout used by every Plan encoding. Private
/// fields prevent callers constructing an unchecked offset/count combination.
#[derive(Clone, Copy)]
pub struct Layout {
    length: usize,
    payload: usize,
    count: usize,
}
impl Layout {
    pub fn new(length: usize, mtu: u16) -> Result<Self, Error> {
        if length < 2 || length > LOGICAL_MTU as usize {
            return Err(Error::Length);
        }
        if length <= mtu as usize {
            return Ok(Self {
                length,
                payload: 0,
                count: 1,
            });
        }
        if mtu <= 4 {
            return Err(Error::Mtu);
        }
        let payload = mtu as usize - 4;
        // ceil((length-2)/payload), after proving length>mtu>=5. Avoid
        // unchecked rounding addition and keep the production bound explicit.
        let count = (length - 3) / payload + 1;
        if !(2..=MAX_PARTS).contains(&count) {
            return Err(Error::Capacity);
        }
        Ok(Self {
            length,
            payload,
            count,
        })
    }
    pub fn count(&self) -> usize {
        self.count
    }
    pub fn bounds(&self, index: usize) -> Result<(usize, usize, usize), Error> {
        if index >= self.count {
            return Err(Error::Sequence);
        }
        if self.count == 1 {
            return Ok((0, self.length, self.length));
        }
        let start = 2 + index * self.payload;
        let limit = start + self.payload;
        let end = if limit < self.length {
            limit
        } else {
            self.length
        };
        Ok((start, end, 4 + end - start))
    }
}
pub struct Plan<'a> {
    raw: &'a [u8],
    layout: Layout,
}
impl<'a> Plan<'a> {
    pub fn new(raw: &'a [u8], mtu: u16, sequenced: bool) -> Result<Self, Error> {
        let layout = Layout::new(raw.len(), mtu)?;
        if layout.count() > 1 {
            if !sequenced || !supported(raw[0]) || raw[1] & 3 != 3 {
                return Err(Error::Unsupported);
            }
            if raw[0] == 13 && raw[1] & 0x18 != 0 {
                return Err(Error::Control);
            }
        }
        Ok(Self { raw, layout })
    }
    pub fn count(&self) -> usize {
        self.layout.count()
    }

    /// Validate index and capacity before touching caller-owned output. Only
    /// the last fragment uses immediate-write; earlier ones are partial-write.
    pub fn encode(&self, index: usize, output: &mut [u8]) -> Result<usize, Error> {
        let (start, end, size) = self.layout.bounds(index)?;
        if self.layout.count() == 1 {
            if output.len() < self.raw.len() {
                return Err(Error::Output);
            }
            output[..self.raw.len()].copy_from_slice(self.raw);
            return Ok(self.raw.len());
        }
        if output.len() < size {
            return Err(Error::Output);
        }
        let last = index + 1 == self.layout.count();
        output[0] = self.raw[0] | 0x80;
        output[1] = (self.raw[1] & !3)
            | if index == 0 {
                0
            } else if last {
                2
            } else {
                1
            };
        if self.raw[0] == 13 && !last {
            output[1] |= 8;
        }
        output[2] = if index == 0 || last {
            self.layout.count() as u8
        } else {
            index as u8
        };
        output[3] = 0; // Transaction numbers were not negotiated.
        output[4..size].copy_from_slice(&self.raw[start..end]);
        Ok(size)
    }
}

#[derive(Debug, PartialEq, Eq)]
pub struct Complete<C, D> {
    pub bytes: Vec<u8>,
    pub context: C,
    pub deadline: D,
}
struct Active<C, D> {
    context: C,
    deadline: D,
    opcode: u8,
    control: u8,
    total: u8,
    next: u8,
    size: usize,
}
/// One lane of one existing physical Session. A receive error clears the
/// partial value; the actor must retire rather than reuse an ambiguous stream.
pub struct Reassembly<C, D> {
    bytes: [u8; LOGICAL_MTU as usize],
    active: Option<Active<C, D>>,
}
impl<C, D> Default for Reassembly<C, D> {
    fn default() -> Self {
        Self {
            bytes: [0; LOGICAL_MTU as usize],
            active: None,
        }
    }
}
impl<C: Copy + Eq, D: Copy + Ord> Reassembly<C, D> {
    pub fn deadline(&self) -> Option<D> {
        self.active.as_ref().map(|a| a.deadline)
    }
    pub fn receive(
        &mut self,
        raw: &[u8],
        mtu: u16,
        negotiated: bool,
        context: C,
        now: D,
        original_deadline: D,
    ) -> Result<Option<Complete<C, D>>, Error> {
        let result = self.apply(raw, mtu, negotiated, context, now, original_deadline);
        if result.is_err() {
            self.active = None;
        }
        result
    }
    fn apply(
        &mut self,
        raw: &[u8],
        mtu: u16,
        negotiated: bool,
        context: C,
        now: D,
        original_deadline: D,
    ) -> Result<Option<Complete<C, D>>, Error> {
        if raw.len() < 4 || raw.len() > usize::from(mtu) {
            return Err(Error::Length);
        }
        let op = raw[0] & 0x7f;
        if !negotiated || !supported(op) || raw[0] & 0x80 == 0 {
            return Err(Error::Unsupported);
        }
        if raw[2] & 0xf0 != 0 || raw[3] != 0 {
            return Err(Error::Control);
        }
        let kind = raw[1] & 3;
        if kind != 3 && raw.len() == 4 {
            return Err(Error::Length);
        }
        let mut control = raw[1] | 3;
        if op == 13 {
            if raw[1] & 0x18 != if kind <= 1 { 8 } else { 0 } {
                return Err(Error::Control);
            }
            control &= !0x18;
        }
        if kind == 3 {
            if self.active.is_some() {
                return Err(Error::Interleaved);
            }
            if raw[2] != 0 {
                return Err(Error::Sequence);
            }
            if now >= original_deadline {
                return Err(Error::Expired);
            }
            let mut bytes = Vec::with_capacity(raw.len() - 2);
            bytes.extend_from_slice(&[op, control]);
            bytes.extend_from_slice(&raw[4..]);
            return Ok(Some(Complete {
                bytes,
                context,
                deadline: original_deadline,
            }));
        }
        if kind == 0 {
            if self.active.is_some() {
                return Err(Error::Interleaved);
            }
            if !(2..=MAX_PARTS as u8).contains(&raw[2]) {
                return Err(Error::Sequence);
            }
            if now >= original_deadline {
                return Err(Error::Expired);
            }
            self.bytes[..2].copy_from_slice(&[op, control]);
            self.active = Some(Active {
                context,
                deadline: original_deadline,
                opcode: op,
                control,
                total: raw[2],
                next: 1,
                size: 2,
            });
        }
        let active = self.active.as_mut().ok_or(Error::Sequence)?;
        if now >= active.deadline {
            return Err(Error::Expired);
        }
        if active.context != context {
            return Err(Error::Identity);
        }
        if active.opcode != op || active.control != control {
            return Err(Error::Interleaved);
        }
        if kind == 1 && (raw[2] != active.next || active.next >= active.total - 1)
            || kind == 2 && (raw[2] != active.total || active.next != active.total - 1)
        {
            return Err(Error::Sequence);
        }
        let size = active
            .size
            .checked_add(raw.len() - 4)
            .ok_or(Error::Capacity)?;
        if size > self.bytes.len() {
            return Err(Error::Capacity);
        }
        self.bytes[active.size..size].copy_from_slice(&raw[4..]);
        active.size = size;
        if kind == 2 {
            let active = self.active.take().expect("checked active assembly");
            return Ok(Some(Complete {
                bytes: self.bytes[..active.size].to_vec(),
                context: active.context,
                deadline: active.deadline,
            }));
        }
        if kind == 1 {
            active.next += 1;
        }
        Ok(None)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn real_value_shapes_roundtrip_with_frozen_identity_and_first_deadline() {
        for op in [8, 9, 11, 13, 14] {
            for mtu in [6, 16, 249, 2042] {
                for n in [5, 16, 32, 249, 250, 254, 255, 1024, 2042, 2047] {
                    let mut raw = vec![0xa5; n];
                    raw[0] = op;
                    raw[1] = if op == 13 { 35 } else { 3 };
                    let Ok(plan) = Plan::new(&raw, mtu, true) else {
                        continue;
                    };
                    if plan.count() == 1 {
                        continue;
                    }
                    let mut rx = Reassembly::default();
                    let mut complete = None;
                    for i in 0..plan.count() {
                        let mut packet = vec![0; usize::from(mtu)];
                        let n = plan.encode(i, &mut packet).unwrap();
                        packet.truncate(n);
                        complete = rx
                            .receive(&packet, mtu, true, (7, 11, 3), i as u64, 100 + i as u64)
                            .unwrap();
                        if i + 1 < plan.count() {
                            assert!(complete.is_none());
                            assert_eq!(rx.deadline(), Some(100));
                        }
                    }
                    let complete = complete.unwrap();
                    assert_eq!(complete.bytes, raw);
                    assert_eq!(complete.deadline, 100);
                    assert_eq!(complete.context, (7, 11, 3));
                    assert_eq!(rx.deadline(), None);
                }
            }
        }
    }
    #[test]
    fn sequence_receipt_deadline_and_size_errors_clear_without_a_complete_value() {
        let raw = [13, 35, 1, 0, 0, 1, 2, 3, 4, 5, 6, 7];
        let plan = Plan::new(&raw, 6, true).unwrap();
        let parts = (0..plan.count())
            .map(|i| {
                let mut p = vec![0; 6];
                let n = plan.encode(i, &mut p).unwrap();
                p.truncate(n);
                p
            })
            .collect::<Vec<_>>();
        for mode in 0..9 {
            let mut rx = Reassembly::default();
            assert!(
                rx.receive(&parts[0], 6, true, 7, 0u64, 10)
                    .unwrap()
                    .is_none()
            );
            let mut next = parts[1].clone();
            let mut context = 7;
            let mut now = 1;
            match mode {
                0 => next = parts[0].clone(),
                1 => next = parts[2].clone(),
                2 => next[1] ^= 32,
                3 => context = 8,
                4 => now = 10,
                5 => next[2] = 15,
                6 => next[3] = 1,
                7 => next[1] &= !8,
                _ => next[2] |= 128,
            }
            assert!(
                rx.receive(&next, 6, true, context, now, 1000).is_err(),
                "{mode}"
            );
            assert_eq!(rx.deadline(), None);
        }
        let mut output = [0xa5; 4];
        assert_eq!(plan.encode(0, &mut output), Err(Error::Output));
        assert_eq!(output, [0xa5; 4]);
        assert!(Plan::new(&raw, 6, false).is_err());
        assert!(Plan::new(&vec![0; 2048], 2042, true).is_err());
    }
    #[test]
    fn complete_wire_stays_unchanged_and_nonfragment_control_is_not_misclassified() {
        for raw in [&[10, 0, 1, 0, 255, 255, 0, 1, 2][..], &[2, 3, 249, 0, 1, 2]] {
            assert!(!needs_reassembly(raw));
            let plan = Plan::new(raw, 249, false).unwrap();
            let mut output = [0; 249];
            let n = plan.encode(0, &mut output).unwrap();
            assert_eq!(&output[..n], raw);
        }
        let raw = [0x89, 3, 0, 0, 1, 2, 3];
        let c = Reassembly::default()
            .receive(&raw, 249, true, 7, 0u64, 10)
            .unwrap()
            .unwrap();
        assert_eq!(c.bytes, [9, 3, 1, 2, 3]);
    }
}
