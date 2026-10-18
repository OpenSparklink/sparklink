use std::{env,path::PathBuf,process::Command};
fn main(){
 let out=PathBuf::from(env::var("OUT_DIR").unwrap());
 let status=Command::new("python3").arg("generate.py").arg(out.join("actual.rs")).status().expect("production source generator");
 assert!(status.success());
 println!("cargo:rerun-if-changed=../../../linux/net/sparklink/sle_dev.rs");
 println!("cargo:rerun-if-changed=../../../linux/net/sparklink/sle_dli.rs");
 println!("cargo:rerun-if-changed=generate.py");
}
