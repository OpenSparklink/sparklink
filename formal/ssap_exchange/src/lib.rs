// SPDX-License-Identifier: GPL-2.0-only
// Include the production implementation verbatim, not a verification clone.
#[path = "../../../crates/slk-protocol/src/ssap/exchange.rs"]
pub mod exchange;

#[cfg(kani)]
mod proofs {
    use super::exchange::{ExchangeInfo, ExchangeKind, ExtensionCapabilities};

    #[kani::proof]
    #[kani::unwind(16)]
    fn exact_decode_reencode_no_overflow() {
        let bytes: [u8; 11] = kani::any();
        let length: usize = kani::any();
        kani::assume(length <= bytes.len());
        let mtu: u16 = kani::any();
        if let Ok(info) = ExchangeInfo::decode(mtu, &bytes[..length]) {
            let mut output = [0xa5; 11];
            let count = info.encode(mtu, &mut output).unwrap();
            assert_eq!(count, length);
            assert_eq!(ExchangeInfo::decode(mtu, &output[..count]), Ok(info));
            for item in &output[count..] {
                assert_eq!(*item, 0xa5);
            }
        }
    }

    #[kani::proof]
    #[kani::unwind(16)]
    fn failed_encode_does_not_mutate_output() {
        let info = ExchangeInfo {
            kind: if kani::any() {
                ExchangeKind::Request
            } else {
                ExchangeKind::Response
            },
            mtu: if kani::any() { Some(kani::any()) } else { None },
            version: if kani::any() { Some(kani::any()) } else { None },
            extension: if kani::any() {
                Some(ExtensionCapabilities {
                    fragment_sequence: kani::any(),
                    transaction_capacity: if kani::any() { Some(kani::any()) } else { None },
                })
            } else {
                None
            },
            reliable: kani::any(),
        };
        let capacity: usize = kani::any();
        kani::assume(capacity <= 11);
        let mtu: u16 = kani::any();
        let mut output: [u8; 11] = kani::any();
        let original = output;
        match info.encode(mtu, &mut output[..capacity]) {
            Err(_) => assert_eq!(output, original),
            Ok(count) => {
                assert!(count <= capacity);
                assert_eq!(ExchangeInfo::decode(mtu, &output[..count]), Ok(info));
                for index in count..11 {
                    assert_eq!(output[index], original[index]);
                }
            }
        }
    }
}
