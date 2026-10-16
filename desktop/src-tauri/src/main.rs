fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("Unable to start the local voice assistant window");
}
