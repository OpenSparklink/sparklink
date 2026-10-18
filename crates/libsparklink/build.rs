// SPDX-License-Identifier: GPL-2.0-only
fn main() {
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("linux") {
        println!("cargo:rustc-cdylib-link-arg=-Wl,-soname,libsparklink.so.0");
    }
    println!("cargo:rerun-if-changed=build.rs");
}
