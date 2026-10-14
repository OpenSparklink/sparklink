#[path = "../../../crates/slk-protocol/src/ssap/value.rs"]
pub mod value;
#[cfg(kani)]
mod proofs {
    use super::value::ValuePdu;
    #[kani::proof]
    #[kani::unwind(20)]
    fn exact_valid_decode_reencode() {
        let input: [u8; 16] = kani::any();
        let len: usize = kani::any();
        kani::assume(len <= 16);
        let mtu: u16 = kani::any();
        if let Ok(p) = ValuePdu::decode(mtu, &input[..len]) {
            let mut output = [0xa5; 16];
            let n = p.encode(mtu, &mut output).unwrap();
            assert!(n == len);
            for i in 0..16 {
                if i < n {
                    assert!(output[i] == input[i]);
                } else {
                    assert!(output[i] == 0xa5);
                }
            }
        }
    }
    #[kani::proof]
    #[kani::unwind(20)]
    fn failed_encode_is_atomic() {
        let input: [u8; 16] = kani::any();
        let len: usize = kani::any();
        kani::assume(len <= 16);
        let mtu: u16 = kani::any();
        let capacity: usize = kani::any();
        kani::assume(capacity <= 16);
        if let Ok(p) = ValuePdu::decode(65535, &input[..len]) {
            let mut output: [u8; 16] = kani::any();
            let original = output;
            if p.encode(mtu, &mut output[..capacity]).is_err() {
                for i in 0..16 {
                    assert!(output[i] == original[i]);
                }
            }
        }
    }
}
