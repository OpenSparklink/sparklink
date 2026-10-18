// SPDX-License-Identifier: GPL-2.0-only
// Logic included from production. Dependency info/stats/logger fixtures only.
include!(concat!(env!("OUT_DIR"), "/actual.rs"));

#[cfg(kani)]
#[kani::proof]
#[kani::unwind(18)]
fn initial_registry_is_empty_and_pending_registration_never_claims_up(){
 let mut registry=SleDevRegistry::new();
 assert_eq!(registry.allocated,0);assert_eq!(registry.next_generation,1);
 assert!(registry.slots.iter().all(Option::is_none));
 let id=registry.register_pending(&SleControllerInfo::default()).unwrap();
 assert_eq!(id,0);assert_eq!(registry.allocated,1);assert_eq!(registry.next_generation,2);
 let dev=registry.slots[0].as_ref().unwrap();
 assert_eq!(dev.generation,1);assert_eq!(dev.flags.load(Ordering::Relaxed),SLE_DEV_SETUP);
}

#[cfg(kani)]
#[kani::proof]
#[kani::unwind(18)]
fn allocator_preserves_occupied_slots_and_fails_closed_at_capacity_or_generation_limit(){
 let bitmap:u16=kani::any();let generation:u64=kani::any();kani::assume(generation>=2);
 let mut registry=SleDevRegistry::new();registry.allocated=bitmap;registry.next_generation=generation;
 for id in 0..SLE_DEV_MAX{
  if bitmap&(1<<id)!=0{registry.slots[id]=Some(SleDev::new(id as u16,generation-1,&SleControllerInfo::default()));}
 }
 let result=registry.register_pending(&SleControllerInfo::default());
 if bitmap==u16::MAX || generation==u64::MAX{
  assert_eq!(result,Err(ENOSPC));assert_eq!(registry.allocated,bitmap);assert_eq!(registry.next_generation,generation);
 }else{
  let id=result.unwrap();assert_eq!(id,(!bitmap).trailing_zeros() as u16);
  assert_eq!(registry.allocated,bitmap|(1<<id));assert_eq!(registry.next_generation,generation+1);
  let dev=registry.slots[id as usize].as_ref().unwrap();assert_eq!(dev.generation,generation);assert_eq!(dev.flags.load(Ordering::Relaxed),SLE_DEV_SETUP);
 }
 for id in 0..SLE_DEV_MAX{
  if bitmap&(1<<id)!=0{let dev=registry.slots[id].as_ref().unwrap();assert_eq!(dev.id,id as u16);assert_eq!(dev.generation,generation-1);}
 }
}
