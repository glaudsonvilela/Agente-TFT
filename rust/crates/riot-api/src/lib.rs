use std::time::Duration;

use reqwest::{
    header::{HeaderMap, HeaderValue, RETRY_AFTER},
    Client, StatusCode,
};
use serde_json::Value;
use thiserror::Error;

const RIOT_TOKEN_HEADER: &str = "X-Riot-Token";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PlatformRoute {
    Br1,
    Eun1,
    Euw1,
    Jp1,
    Kr,
    La1,
    La2,
    Na1,
    Oc1,
    Tr1,
    Ru,
    Ph2,
    Sg2,
    Th2,
    Tw2,
    Vn2,
}

impl PlatformRoute {
    pub const fn host(self) -> &'static str {
        match self {
            Self::Br1 => "br1.api.riotgames.com",
            Self::Eun1 => "eun1.api.riotgames.com",
            Self::Euw1 => "euw1.api.riotgames.com",
            Self::Jp1 => "jp1.api.riotgames.com",
            Self::Kr => "kr.api.riotgames.com",
            Self::La1 => "la1.api.riotgames.com",
            Self::La2 => "la2.api.riotgames.com",
            Self::Na1 => "na1.api.riotgames.com",
            Self::Oc1 => "oc1.api.riotgames.com",
            Self::Tr1 => "tr1.api.riotgames.com",
            Self::Ru => "ru.api.riotgames.com",
            Self::Ph2 => "ph2.api.riotgames.com",
            Self::Sg2 => "sg2.api.riotgames.com",
            Self::Th2 => "th2.api.riotgames.com",
            Self::Tw2 => "tw2.api.riotgames.com",
            Self::Vn2 => "vn2.api.riotgames.com",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RegionalRoute {
    Americas,
    Asia,
    Europe,
    Sea,
}

impl RegionalRoute {
    pub const fn host(self) -> &'static str {
        match self {
            Self::Americas => "americas.api.riotgames.com",
            Self::Asia => "asia.api.riotgames.com",
            Self::Europe => "europe.api.riotgames.com",
            // Some API families use SEA routing even when the TFT docs focus on the
            // three traditional regional clusters. Keeping the enum explicit makes
            // routing configurable without stringly-typed hosts.
            Self::Sea => "sea.api.riotgames.com",
        }
    }
}

#[derive(Debug, Clone)]
pub struct RiotApiConfig {
    pub platform: PlatformRoute,
    pub regional: RegionalRoute,
    pub request_timeout: Duration,
    pub pool_idle_timeout: Duration,
}

impl Default for RiotApiConfig {
    fn default() -> Self {
        Self {
            platform: PlatformRoute::Br1,
            regional: RegionalRoute::Americas,
            request_timeout: Duration::from_secs(3),
            pool_idle_timeout: Duration::from_secs(30),
        }
    }
}

#[derive(Debug, Error)]
pub enum RiotApiError {
    #[error("Riot API key cannot be empty")]
    EmptyApiKey,
    #[error("invalid Riot API key header value")]
    InvalidApiKey,
    #[error("Riot API request failed: {0}")]
    Transport(String),
    #[error("Riot API authentication failed with status {0}")]
    Authentication(u16),
    #[error("Riot API rate limited the request")]
    RateLimited { retry_after_seconds: Option<u64> },
    #[error("Riot API returned HTTP {status}: {body}")]
    Http { status: u16, body: String },
    #[error("Riot API returned invalid JSON: {0}")]
    InvalidJson(String),
}

#[derive(Clone)]
pub struct RiotApiClient {
    http: Client,
    token: HeaderValue,
    config: RiotApiConfig,
}

impl RiotApiClient {
    pub fn new(api_key: impl AsRef<str>, config: RiotApiConfig) -> Result<Self, RiotApiError> {
        let api_key = api_key.as_ref().trim();
        if api_key.is_empty() {
            return Err(RiotApiError::EmptyApiKey);
        }

        let token = HeaderValue::from_str(api_key).map_err(|_| RiotApiError::InvalidApiKey)?;
        let http = Client::builder()
            .timeout(config.request_timeout)
            .pool_idle_timeout(config.pool_idle_timeout)
            .tcp_keepalive(Duration::from_secs(30))
            .build()
            .map_err(|e| RiotApiError::Transport(e.to_string()))?;

        Ok(Self {
            http,
            token,
            config,
        })
    }

    pub fn config(&self) -> &RiotApiConfig {
        &self.config
    }

    pub fn active_game_url(&self, puuid: &str) -> String {
        format!(
            "https://{}/lol/spectator/tft/v5/active-games/by-puuid/{}",
            self.config.platform.host(),
            puuid
        )
    }

    pub fn match_ids_url(&self, puuid: &str) -> String {
        format!(
            "https://{}/tft/match/v1/matches/by-puuid/{}/ids",
            self.config.regional.host(),
            puuid
        )
    }

    pub fn match_url(&self, match_id: &str) -> String {
        format!(
            "https://{}/tft/match/v1/matches/{}",
            self.config.regional.host(),
            match_id
        )
    }

    pub async fn active_tft_game_by_puuid(
        &self,
        puuid: &str,
    ) -> Result<Option<Value>, RiotApiError> {
        let response = self
            .request(self.http.get(self.active_game_url(puuid)))
            .await?;

        if response.status() == StatusCode::NOT_FOUND {
            return Ok(None);
        }

        Ok(Some(parse_json_response(response).await?))
    }

    pub async fn tft_match_ids_by_puuid(
        &self,
        puuid: &str,
        start: u32,
        count: u32,
    ) -> Result<Vec<String>, RiotApiError> {
        let response = self
            .request(
                self.http
                    .get(self.match_ids_url(puuid))
                    .query(&[("start", start), ("count", count.clamp(1, 100))]),
            )
            .await?;

        let value = parse_json_response(response).await?;
        serde_json::from_value(value).map_err(|e| RiotApiError::InvalidJson(e.to_string()))
    }

    pub async fn tft_match_by_id(&self, match_id: &str) -> Result<Value, RiotApiError> {
        let response = self
            .request(self.http.get(self.match_url(match_id)))
            .await?;
        parse_json_response(response).await
    }

    async fn request(
        &self,
        builder: reqwest::RequestBuilder,
    ) -> Result<reqwest::Response, RiotApiError> {
        let response = builder
            .header(RIOT_TOKEN_HEADER, self.token.clone())
            .send()
            .await
            .map_err(|e| RiotApiError::Transport(e.to_string()))?;

        match response.status() {
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
                return Err(RiotApiError::Authentication(response.status().as_u16()));
            }
            StatusCode::TOO_MANY_REQUESTS => {
                return Err(RiotApiError::RateLimited {
                    retry_after_seconds: retry_after_seconds(response.headers()),
                });
            }
            status if status.is_client_error() || status.is_server_error() => {
                // Active-game 404 is handled by its public method before this helper
                // is used for the generic error branch, so preserve 404 responses.
                if status == StatusCode::NOT_FOUND {
                    return Ok(response);
                }

                let status_code = status.as_u16();
                let body = response.text().await.unwrap_or_default();
                return Err(RiotApiError::Http {
                    status: status_code,
                    body: truncate_body(body),
                });
            }
            _ => {}
        }

        Ok(response)
    }
}

fn retry_after_seconds(headers: &HeaderMap) -> Option<u64> {
    headers
        .get(RETRY_AFTER)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<u64>().ok())
}

async fn parse_json_response(response: reqwest::Response) -> Result<Value, RiotApiError> {
    let status = response.status();

    if status == StatusCode::NOT_FOUND {
        let body = response.text().await.unwrap_or_default();
        return Err(RiotApiError::Http {
            status: 404,
            body: truncate_body(body),
        });
    }

    response
        .json::<Value>()
        .await
        .map_err(|e| RiotApiError::InvalidJson(e.to_string()))
}

fn truncate_body(mut body: String) -> String {
    const MAX: usize = 512;
    if body.len() > MAX {
        body.truncate(MAX);
        body.push_str("…");
    }
    body
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn brazil_defaults_to_br1_and_americas() {
        let config = RiotApiConfig::default();
        assert_eq!(config.platform, PlatformRoute::Br1);
        assert_eq!(config.regional, RegionalRoute::Americas);
    }

    #[test]
    fn builds_expected_tft_urls() {
        let client = RiotApiClient::new("RGAPI-test", RiotApiConfig::default()).unwrap();

        assert_eq!(
            client.active_game_url("puuid"),
            "https://br1.api.riotgames.com/lol/spectator/tft/v5/active-games/by-puuid/puuid"
        );
        assert_eq!(
            client.match_ids_url("puuid"),
            "https://americas.api.riotgames.com/tft/match/v1/matches/by-puuid/puuid/ids"
        );
        assert_eq!(
            client.match_url("BR1_123"),
            "https://americas.api.riotgames.com/tft/match/v1/matches/BR1_123"
        );
    }

    #[test]
    fn rejects_empty_api_key() {
        assert!(matches!(
            RiotApiClient::new("  ", RiotApiConfig::default()),
            Err(RiotApiError::EmptyApiKey)
        ));
    }

    #[test]
    fn parses_retry_after_header() {
        let mut headers = HeaderMap::new();
        headers.insert(RETRY_AFTER, HeaderValue::from_static("7"));
        assert_eq!(retry_after_seconds(&headers), Some(7));
    }

    #[test]
    fn truncates_large_error_bodies() {
        let text = "x".repeat(1000);
        let truncated = truncate_body(text);
        assert!(truncated.len() < 600);
        assert!(truncated.ends_with('…'));
    }
}
