#[derive(kani::Arbitrary)]
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
#[repr(C, align(8))]
pub struct SleRegistrationSnapshot {
    pub generation: u64,
    pub version: u32,
    pub state: u32,
    pub profile: u32,
    pub phase: u32,
    pub error: i32,
    pub dev_index: u16,
    pub bus: u8,
    pub reserved_byte: u8,
    pub reserved: [u8; 8],
}
pub const REGISTRATION_VERSION: u32 = 1;
pub const REGISTRATION_PENDING: u32 = 1;
pub const REGISTRATION_FAULT: u32 = 2;
pub const REGISTRATION_INSTALLED: u32 = 3;
pub const REGISTRATION_RETIRING: u32 = 4;
impl SleRegistrationSnapshot {
    pub fn valid_for(&self, index: u16, generation: u64) -> bool {
        self.version == REGISTRATION_VERSION
            && self.generation != 0
            && (generation == generation)
            && index < 16
            && self.dev_index == index
            && self.bus <= 6
            && self.reserved_byte == 0
            && self.reserved == [0; 8]
            && match self.state {
                REGISTRATION_PENDING => self.error == 0,
                REGISTRATION_FAULT => self.error < 0,
                REGISTRATION_INSTALLED | REGISTRATION_RETIRING => {
                    self.phase == 0 && self.error == 0
                }
                _ => false,
            }
    }
}

#[kani::proof]
fn accepted_observation_preserves_identity_and_diagnostics() {
    let s: SleRegistrationSnapshot = kani::any();
    let index: u16 = kani::any();
    let generation: u64 = kani::any();
    if s.valid_for(index, generation) {
        assert!(index < 16 && s.dev_index == index);
        assert!(s.generation != 0);
        assert!(generation == 0 || s.generation == generation);
        assert!(s.version == 1 && s.bus <= 6);
        assert!(s.reserved_byte == 0 && s.reserved == [0; 8]);
        match s.state {
            1 => { assert!(s.error == 0); },
            2 => { assert!(s.error < 0); },
            3 | 4 => { assert!(s.phase == 0 && s.error == 0); },
            _ => panic!("unknown registration state accepted"),
        }
    }
}
