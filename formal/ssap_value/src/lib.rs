#[path = "../../../crates/slk-protocol/src/ssap/value.rs"]
pub mod value;
#[path = "../../../crates/slk-protocol/src/ssap/read_uuid.rs"]
pub mod read_uuid;
#[path = "../../../crates/slk-protocol/src/ssap/updates.rs"]
pub mod updates;
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

#[cfg(kani)]
mod uuid_proofs {
    #[kani::proof]
    #[kani::unwind(20)]
    fn actual_uuid_response_roundtrip_and_atomic_refusal() {
        let raw:[u8;16]=kani::any();let len:usize=kani::any();kani::assume(len<=16);
        if let Ok(items)=super::read_uuid::decode(16,&raw[..len]) {
            let mut out=[0xa5;16];let n=super::read_uuid::encode(16,&items,&mut out).unwrap();assert_eq!(&out[..n],&raw[..len]);
            let capacity:usize=kani::any();kani::assume(capacity<=16);let before=out;
            if super::read_uuid::encode(16,&items,&mut out[..capacity]).is_err(){assert_eq!(out,before);}
        }
    }
}

#[cfg(kani)]
mod ack_proofs {
    #[kani::proof]
    #[kani::unwind(12)]
    fn actual_ack_flags_and_atomic_refusal() {
        let flags:[u8;4]=kani::any();let count:usize=kani::any();kani::assume(count<=4);
        let capacity:usize=kani::any();kani::assume(capacity<=8);
        let mtu:u16=kani::any();let event:bool=kani::any();let mut out:[u8;8]=kani::any();let before=out;
        match super::updates::ack(mtu,event,&flags[..count],&mut out[..capacity]) {
            Ok(n)=>{
                assert!(n==count+2);assert!(out[0]==17);assert!(out[1]==if event{7}else{3});
                match super::updates::decode_ack(mtu,&out[..n],event,count) {
                    Ok(decoded)=>{for i in 0..count {assert!(decoded[i]==flags[i]);assert!(flags[i]<=1);}},
                    Err(_)=>assert!(false,"encoded ACK must decode"),
                }
                for i in n..8 {assert!(out[i]==before[i]);}
            },
            Err(_)=>{for i in 0..8 {assert!(out[i]==before[i]);}},
        }
    }
}
