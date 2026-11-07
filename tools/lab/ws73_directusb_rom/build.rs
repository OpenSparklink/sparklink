// SPDX-License-Identifier: GPL-2.0-only
//! Compile the exact existing production authority, not a second state machine.
use std::{
    env, fs,
    io::{Read, Write},
    path::PathBuf,
    process::{Command, Stdio},
};

fn main() {
    println!("cargo:rerun-if-env-changed=SPARKLINK_KERNEL_SOURCE");
    println!("cargo:rustc-check-cfg=cfg(kani)");
    let root = PathBuf::from(
        env::var_os("SPARKLINK_KERNEL_SOURCE")
            .expect("explicit SPARKLINK_KERNEL_SOURCE with pinned production authority required"),
    )
    .canonicalize()
    .expect("kernel source root");
    let source = root
        .join("net/sparklink/sle_grant.rs")
        .canonicalize()
        .expect("actual kernel lease authority source");
    assert!(
        source.starts_with(&root),
        "authority source escapes selected kernel root"
    );
    let mut bytes = Vec::new();
    fs::File::open(&source)
        .expect("production source file")
        .take(65537)
        .read_to_end(&mut bytes)
        .expect("bounded production source snapshot");
    assert!(
        bytes.len() <= 65536,
        "production authority source exceeds build input budget"
    );
    let mut git = Command::new("git")
        .args(["hash-object", "--stdin"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("git content hash for production source");
    git.stdin
        .take()
        .expect("git stdin")
        .write_all(&bytes)
        .expect("hash exact snapshot");
    let output = git
        .wait_with_output()
        .expect("production source hash result");
    assert!(
        output.status.success() && output.stderr.is_empty(),
        "cannot verify authority source"
    );
    assert_eq!(
        String::from_utf8(output.stdout).expect("git output").trim(),
        "3bfd18a8f6698fffc7be5601ecb7d01012261a33",
        "production authority pin mismatch"
    );
    println!("cargo:rerun-if-changed={}", source.display());
    let out = PathBuf::from(env::var_os("OUT_DIR").expect("Cargo OUT_DIR"));
    // Compile exactly the bytes checked above, even if the selected worktree
    // changes later. This generated snapshot has no independent implementation.
    let snapshot = out.join("production_lease_source.rs");
    fs::write(&snapshot, bytes).expect("exact verified production source snapshot");
    let source = snapshot.to_str().expect("UTF-8 source path required");
    let generated = out.join("production_authority.rs");
    fs::write(
        generated,
        format!("#[path = {source:?}] mod production_lease;\n"),
    )
    .expect("production module reference");
}
