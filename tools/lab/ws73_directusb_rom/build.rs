// SPDX-License-Identifier: GPL-2.0-only
//! Build exact existing production authority and wire bytes, not new algorithms.
use std::{
    env, fs,
    io::{Read, Write},
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

fn pinned(root: &Path, relative: &str, expected: &str, limit: usize, label: &str) -> Vec<u8> {
    let source = root
        .join(relative)
        .canonicalize()
        .expect("selected production source");
    assert!(
        source.starts_with(root),
        "{label} source escapes selected kernel root"
    );
    let mut bytes = Vec::new();
    fs::File::open(&source)
        .expect("production source file")
        .take(limit as u64 + 1)
        .read_to_end(&mut bytes)
        .expect("bounded production snapshot");
    assert!(
        bytes.len() <= limit,
        "{label} source exceeds build input budget"
    );
    let mut git = Command::new("git")
        .args(["hash-object", "--stdin"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("git production content hash");
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
        "cannot verify {label} source"
    );
    assert_eq!(
        String::from_utf8(output.stdout).expect("git output").trim(),
        expected,
        "{label} pin mismatch"
    );
    println!("cargo:rerun-if-changed={}", source.display());
    bytes
}
fn checked(command: &mut Command) {
    let result = command.output().expect("selected native C tool");
    assert!(
        result.status.success(),
        "native C build failed: {command:?}\n{}\n{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}
fn main() {
    println!("cargo:rerun-if-env-changed=SPARKLINK_KERNEL_SOURCE");
    println!("cargo:rerun-if-env-changed=CC");
    println!("cargo:rerun-if-env-changed=AR");
    println!("cargo:rustc-check-cfg=cfg(kani)");
    let root = PathBuf::from(
        env::var_os("SPARKLINK_KERNEL_SOURCE")
            .expect("explicit SPARKLINK_KERNEL_SOURCE with pinned production source required"),
    )
    .canonicalize()
    .expect("kernel source root");
    // Verify every input before publishing generated source. Compile only these
    // owned snapshots, never reread a worktree after its hash was accepted.
    let authority = pinned(
        &root,
        "net/sparklink/sle_grant.rs",
        "3bfd18a8f6698fffc7be5601ecb7d01012261a33",
        65536,
        "production authority",
    );
    let wire = pinned(
        &root,
        "drivers/sparklink/ws73/wire.c",
        "7ed82b5448acd03b1126e3fe2649f50028fcc05b",
        65536,
        "production wire codec",
    );
    let header = pinned(
        &root,
        "drivers/sparklink/ws73/wire.h",
        "d836b3055f4d82b7449ce19e6399c9384527f2b1",
        16384,
        "production wire header",
    );
    let out = PathBuf::from(env::var_os("OUT_DIR").expect("Cargo OUT_DIR"));
    let snapshot = out.join("production_lease_source.rs");
    fs::write(&snapshot, authority).expect("verified production authority snapshot");
    fs::write(
        out.join("production_authority.rs"),
        format!(
            "#[path = {:?}] mod production_lease;\n",
            snapshot.to_str().expect("UTF-8 source path")
        ),
    )
    .expect("production module reference");
    fs::write(out.join("wire.c"), wire).expect("verified production wire snapshot");
    fs::write(out.join("wire.h"), header).expect("verified production header snapshot");
    // This explicit native compiler adapter currently supports our Linux x64
    // qualification target only. MSVC check does not compile/link/run this C.
    if env::var("CARGO_CFG_TARGET_OS").expect("Cargo target OS") == "linux" {
        assert_eq!(
            env::var("HOST").expect("Cargo HOST"),
            "x86_64-unknown-linux-gnu",
            "native C compiler host not supported"
        );
        assert_eq!(
            env::var("TARGET").expect("Cargo TARGET"),
            "x86_64-unknown-linux-gnu",
            "native C compiler target not supported"
        );
        let object = out.join("ws73_wire.o");
        checked(
            Command::new(env::var_os("CC").unwrap_or_else(|| "cc".into()))
                .args(["-std=c11", "-Wall", "-Wextra", "-Werror", "-fPIC", "-c"])
                .arg(out.join("wire.c"))
                .arg("-o")
                .arg(&object),
        );
        let archive = out.join("libws73_wire.a");
        checked(
            Command::new(env::var_os("AR").unwrap_or_else(|| "ar".into()))
                .arg("crs")
                .arg(&archive)
                .arg(object),
        );
        println!("cargo:rustc-link-search=native={}", out.display());
        println!("cargo:rustc-link-lib=static=ws73_wire");
    }
}
