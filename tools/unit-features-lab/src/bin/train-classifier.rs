fn main() {
    if let Err(error) = agente_tft_unit_features_lab::training::run_cli() {
        eprintln!("CLASSIFIER_TRAINING_ERROR: {error}");
        std::process::exit(1);
    }
}
