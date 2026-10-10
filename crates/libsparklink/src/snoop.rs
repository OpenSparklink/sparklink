//! Privileged, independently selected, non-consuming DLI seam observation.
use crate::{Error, Result};

/// A capture is private and never overwrites existing evidence.
pub fn create_snoop_capture(
    path: impl AsRef<std::path::Path>,
) -> std::io::Result<std::io::BufWriter<std::fs::File>> {
    use std::os::unix::fs::OpenOptionsExt;
    let file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    Ok(std::io::BufWriter::new(file))
}
use slk_protocol::{
    SNOOP_PAYLOAD_MAX, SNOOP_TRUNCATED, SNOOP_VERSION, SleSnoopQuery, SleSnoopRecord, ioctl,
};
use std::{
    io::Write,
    os::fd::{AsRawFd, OwnedFd, RawFd},
};
use tokio::io::unix::AsyncFd;

#[derive(Clone, Copy, Debug)]
pub struct SnoopCursor {
    pub generation: u64,
    pub after_seq: u64,
}

fn validate(record: &SleSnoopRecord, cursor: &SnoopCursor, index: u16) -> Result<()> {
    let n = usize::from(record.captured_length);
    if record.seq <= cursor.after_seq
        || record.generation != cursor.generation
        || record.generation == 0
        || record.dev_index != index
        || record.profile != 1
        || record.format != 1
        || record.timestamp_ns == 0
        || !matches!(record.direction, 1 | 2)
        || record.status > 0
        || (record.direction == 1 && record.status != 0)
        || record.original_length == 0
        || n != (record.original_length as usize).min(SNOOP_PAYLOAD_MAX)
        || record.flags
            != if record.original_length as usize > SNOOP_PAYLOAD_MAX {
                SNOOP_TRUNCATED
            } else {
                0
            }
        || record.reserved != 0
        || record.lost != record.seq - cursor.after_seq - 1
        || record.payload[n..].iter().any(|b| *b != 0)
    {
        return Err(Error::InvalidParam("invalid snoop record response"));
    }
    Ok(())
}
pub(crate) fn poll(
    fd: RawFd,
    cursor: &mut SnoopCursor,
    index: u16,
) -> Result<Option<SleSnoopRecord>> {
    if cursor.generation == 0 {
        return Err(Error::InvalidParam("snoop requires explicit generation"));
    }
    // SAFETY: integer-only fixed representation, with a valid zero baseline.
    let mut query: SleSnoopQuery = unsafe { std::mem::zeroed() };
    query.version = SNOOP_VERSION;
    query.generation = cursor.generation;
    query.after_seq = cursor.after_seq;
    match unsafe { ioctl::sl_snoop_get(fd, &mut query) } {
        Ok(_) => {
            if query.version != SNOOP_VERSION
                || query.generation != cursor.generation
                || query.flags != 0
                || query.reserved != 0
            {
                return Err(Error::InvalidParam("invalid snoop query response"));
            }
            validate(&query.record, cursor, index)?;
            cursor.after_seq = query.record.seq;
            Ok(Some(query.record))
        }
        Err(nix::Error::EAGAIN) => Ok(None),
        Err(error) => Err(Error::Ioctl(error)),
    }
}

/// Requires CAP_NET_ADMIN on every query. It never acquires management or
/// falls back to the old raw reply queue. Unplug terminates with ENODEV.
pub struct SnoopReceiver {
    fd: AsyncFd<OwnedFd>,
    cursor: SnoopCursor,
    index: u16,
}
impl SnoopReceiver {
    pub(crate) fn from_fd(fd: OwnedFd, generation: u64, index: u16) -> Result<Self> {
        tokio::runtime::Handle::try_current()
            .map_err(|_| Error::InvalidParam("snoop receiver requires Tokio I/O"))?;
        poll(
            fd.as_raw_fd(),
            &mut SnoopCursor {
                generation,
                after_seq: 0,
            },
            index,
        )?;
        Ok(Self {
            fd: AsyncFd::new(fd).map_err(Error::OpenDevice)?,
            cursor: SnoopCursor {
                generation,
                after_seq: 0,
            },
            index,
        })
    }
    pub fn try_next(&mut self) -> Result<Option<SleSnoopRecord>> {
        poll(self.fd.get_ref().as_raw_fd(), &mut self.cursor, self.index)
    }
    pub async fn next_record(&mut self) -> Result<SleSnoopRecord> {
        loop {
            if let Some(record) = self.try_next()? {
                return Ok(record);
            }
            let mut ready = self.fd.readable().await.map_err(Error::OpenDevice)?;
            ready.clear_ready();
        }
    }
}

/// Portable little-endian fixed-record capture: 16-byte SLKSNP01 header,
/// version/max length, then 376-byte records in UAPI field order. Zero padding
/// is retained. This is a DLI seam format, not PCAP or USB aggregate capture.
pub fn write_snoop_header(out: &mut impl Write) -> std::io::Result<()> {
    out.write_all(b"SLKSNP01")?;
    out.write_all(&SNOOP_VERSION.to_le_bytes())?;
    out.write_all(&(SNOOP_PAYLOAD_MAX as u32).to_le_bytes())
}
pub fn write_snoop_record(out: &mut impl Write, r: &SleSnoopRecord) -> std::io::Result<()> {
    for n in [r.seq, r.generation, r.timestamp_ns, r.lost] {
        out.write_all(&n.to_le_bytes())?;
    }
    for n in [r.profile, r.original_length] {
        out.write_all(&n.to_le_bytes())?;
    }
    out.write_all(&r.status.to_le_bytes())?;
    out.write_all(&r.dev_index.to_le_bytes())?;
    out.write_all(&[r.direction, r.format])?;
    out.write_all(&r.captured_length.to_le_bytes())?;
    out.write_all(&r.flags.to_le_bytes())?;
    out.write_all(&r.reserved.to_le_bytes())?;
    out.write_all(&r.payload)
}

/// Raw WS73 A1 opcode or A2 event code. Other slot types remain opaque.
pub fn snoop_packet_code(r: &SleSnoopRecord) -> Option<u16> {
    if r.captured_length >= 3 && matches!(r.payload[0], 0xa1 | 0xa2) {
        Some(u16::from_le_bytes([r.payload[1], r.payload[2]]))
    } else {
        None
    }
}
pub fn describe_snoop(r: &SleSnoopRecord) -> String {
    let data: String = r.payload[..r.captured_length as usize]
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    format!(
        "SnoopRecord: index={} generation={} seq={} kernel_boottime_ns={} direction={} transport_status={} profile={} format={} captured={} original={} lost={} truncated={} data={}",
        r.dev_index,
        r.generation,
        r.seq,
        r.timestamp_ns,
        if r.direction == 1 { "RX" } else { "TX_RESULT" },
        r.status,
        r.profile,
        r.format,
        r.captured_length,
        r.original_length,
        r.lost,
        u8::from(r.flags & SNOOP_TRUNCATED != 0),
        data
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn capture_is_private_and_preserves_existing_evidence() {
        use std::os::unix::fs::PermissionsExt;
        let path = std::env::temp_dir().join(format!("slk-snoop-private-{}", std::process::id()));
        let mut out = create_snoop_capture(&path).unwrap();
        out.write_all(b"original evidence").unwrap();
        out.flush().unwrap();
        assert_eq!(
            std::fs::metadata(&path).unwrap().permissions().mode() & 0o777,
            0o600
        );
        assert_eq!(
            create_snoop_capture(&path).unwrap_err().kind(),
            std::io::ErrorKind::AlreadyExists
        );
        assert_eq!(std::fs::read(&path).unwrap(), b"original evidence");
        std::fs::remove_file(path).unwrap();
    }
    #[test]
    fn capture_header_and_field_order_are_portable() {
        // SAFETY: all-zero integer/byte representation is valid.
        let mut r: SleSnoopRecord = unsafe { std::mem::zeroed() };
        r.seq = 5;
        r.generation = 7;
        r.timestamp_ns = 9;
        r.lost = 4;
        r.profile = 1;
        r.original_length = 2;
        r.dev_index = 3;
        r.direction = 1;
        r.format = 1;
        r.captured_length = 2;
        r.payload[..2].copy_from_slice(&[0xa2, 1]);
        let mut out = Vec::new();
        write_snoop_header(&mut out).unwrap();
        write_snoop_record(&mut out, &r).unwrap();
        assert_eq!(out.len(), 392);
        assert_eq!(&out[..8], b"SLKSNP01");
        assert_eq!(&out[16..24], &5u64.to_le_bytes());
        assert_eq!(&out[60..64], &[3, 0, 1, 1]);
        assert_eq!(&out[72..74], &[0xa2, 1]);
        let c = SnoopCursor {
            generation: 7,
            after_seq: 0,
        };
        assert!(validate(&r, &c, 3).is_ok());
        r.lost = 0;
        assert!(validate(&r, &c, 3).is_err());
        r.lost = 4;
        r.payload[2] = 1;
        assert!(validate(&r, &c, 3).is_err());
        r.payload[2] = 0;
        r.captured_length = 321;
        assert!(validate(&r, &c, 3).is_err());
    }
    #[test]
    fn truncation_never_masquerades_as_complete() {
        // SAFETY: all-zero integer/byte representation is valid.
        let mut r: SleSnoopRecord = unsafe { std::mem::zeroed() };
        r.seq = 1;
        r.generation = 1;
        r.timestamp_ns = 1;
        r.profile = 1;
        r.original_length = 500;
        r.direction = 1;
        r.format = 1;
        r.captured_length = 320;
        r.flags = SNOOP_TRUNCATED;
        let c = SnoopCursor {
            generation: 1,
            after_seq: 0,
        };
        assert!(validate(&r, &c, 0).is_ok());
        r.flags = 0;
        assert!(validate(&r, &c, 0).is_err());
    }
}
