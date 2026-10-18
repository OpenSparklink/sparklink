fn main() {
    if let Err(error) = slktest::main_entry() {
        eprintln!("error: {error:#}");
        std::process::exit(1);
    }
}
