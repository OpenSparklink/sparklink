"""Shared integer input validation; no device or library access."""
def _unsigned(value, bits, name, nonzero=False):
    if not isinstance(value, int) or not (int(nonzero) <= value < 1 << bits):
        raise ValueError(f"{name} must fit unsigned {bits} bits" + (" and be nonzero" if nonzero else ""))
    return value
