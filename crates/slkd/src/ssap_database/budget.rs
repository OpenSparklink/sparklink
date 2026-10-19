//! Shared local/remote replacement admission; no allocation or mutation.
pub(super) fn replacement_bytes(total: usize, old: usize, new: usize) -> Option<usize> {
    if total > 8192 || old > 2042 || new > 2042 {
        return None;
    }
    total
        .checked_sub(old)?
        .checked_add(new)
        .filter(|next| *next <= 8192)
}
