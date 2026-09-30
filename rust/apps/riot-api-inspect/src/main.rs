use std::{env, process::ExitCode};

use agente_tft_riot_api::{RiotApiClient, RiotApiConfig, RiotApiError};

#[tokio::main]
async fn main() -> ExitCode {
    match run().await {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("{message}");
            ExitCode::FAILURE
        }
    }
}

async fn run() -> Result<(), String> {
    let mut args = env::args().skip(1);

    let Some(game_name) = args.next() else {
        return Err(usage());
    };

    if game_name == "-h" || game_name == "--help" {
        println!("{}", usage());
        return Ok(());
    }

    let tag_line = args.next().ok_or_else(usage)?;
    let history_count: u32 = args
        .next()
        .as_deref()
        .unwrap_or("5")
        .parse()
        .map_err(|_| "history_count must be an integer from 1 to 20".to_string())?;

    if !(1..=20).contains(&history_count) {
        return Err("history_count must be between 1 and 20".into());
    }

    let api_key = env::var("RIOT_API_KEY")
        .map_err(|_| "RIOT_API_KEY is not set in the environment".to_string())?;

    let client = RiotApiClient::new(api_key, RiotApiConfig::default())
        .map_err(format_api_error)?;

    let account = client
        .account_by_riot_id(&game_name, &tag_line)
        .await
        .map_err(format_api_error)?;

    let active_game = client
        .active_tft_game_by_puuid(&account.puuid)
        .await
        .map_err(format_api_error)?;

    let recent_matches = client
        .tft_match_ids_by_puuid(&account.puuid, 0, history_count)
        .await
        .map_err(format_api_error)?;

    let account_label = match (&account.game_name, &account.tag_line) {
        (Some(name), Some(tag)) => format!("{name}#{tag}"),
        _ => format!("{game_name}#{tag_line}"),
    };

    let active_summary = active_game.map(|game| {
        serde_json::json!({
            "in_game": true,
            "game_id": game.game_id,
            "game_length_seconds": game.game_length,
            "queue_id": game.game_queue_config_id,
            "game_start_time_ms": game.game_start_time,
            "map_id": game.map_id,
            "participants": game.participants.len(),
            "self_present": game.participants.iter().any(|p| p.puuid == account.puuid)
        })
    }).unwrap_or_else(|| serde_json::json!({"in_game": false}));

    let output = serde_json::json!({
        "account": account_label,
        "puuid_fingerprint": puuid_fingerprint(&account.puuid),
        "routing": {
            "platform": client.config().platform.host(),
            "regional": client.config().regional.host()
        },
        "active_game": active_summary,
        "recent_match_ids": recent_matches
    });

    println!(
        "{}",
        serde_json::to_string_pretty(&output)
            .map_err(|e| format!("failed to format JSON output: {e}"))?
    );

    Ok(())
}

fn puuid_fingerprint(puuid: &str) -> String {
    let start: String = puuid.chars().take(6).collect();
    let end: String = puuid
        .chars()
        .rev()
        .take(6)
        .collect::<String>()
        .chars()
        .rev()
        .collect();

    if puuid.chars().count() <= 14 {
        puuid.to_string()
    } else {
        format!("{start}…{end}")
    }
}

fn format_api_error(error: RiotApiError) -> String {
    match error {
        RiotApiError::Authentication(_) => (
            "Riot API authentication failed. Check RIOT_API_KEY; development keys expire regularly."
        )
            .to_string(),
        RiotApiError::RateLimited {
            retry_after_seconds,
        } => match retry_after_seconds {
            Some(seconds) => format!(
                "Riot API rate limit reached. Retry after approximately {seconds}s."
            ),
            None => "Riot API rate limit reached. Retry later.".to_string(),
        },
        other => other.to_string(),
    }
}

fn usage() -> String {
    [
        "Usage:",
        "  RIOT_API_KEY=... cargo run --manifest-path rust/Cargo.toml \\",
        "    -p agente-tft-riot-api-inspect -- \\",
        "    \"Game Name\" TAG [history_count]",
        "",
        "Brazil routing defaults:",
        "  platform = BR1",
        "  regional = AMERICAS",
        "",
        "The command does not print the full PUUID; only a short fingerprint.",
    ]
    .join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fingerprints_long_puuid_without_exposing_full_value() {
        let value = "abcdefghijklmnopqrstuvwxyz";
        let fingerprint = puuid_fingerprint(value);
        assert_eq!(fingerprint, "abcdef…uvwxyz");
        assert_ne!(fingerprint, value);
    }

    #[test]
    fn keeps_short_identifier_readable() {
        assert_eq!(puuid_fingerprint("short"), "short");
    }
}
