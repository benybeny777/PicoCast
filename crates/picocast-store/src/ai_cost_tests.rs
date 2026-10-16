#![cfg(test)]
#![allow(clippy::unwrap_used)]

use super::*;
use std::sync::{Arc, Barrier};

fn request(channel: &ChannelId, id: &str) -> AiCostReservation {
    let at = Timestamp::parse("2026-10-16T00:00:00Z").unwrap();
    AiCostReservation {
        channel_id: channel.clone(),
        request_id: id.into(),
        day: UtcDay::from_timestamp(&at),
        daily_budget_micros: 100,
        max_cost_micros: Some(60),
        daily_token_budget: 200,
        max_input_tokens: 50,
        max_output_tokens: 50,
        provider: "fixture".into(),
        model: "fixture-model".into(),
        at,
        project_id: None,
        job_id: None,
    }
}

fn fixture() -> (tempfile::TempDir, crate::StorePaths, Store, ChannelId) {
    let (directory, paths, store) = crate::tests::fixture();
    let channel = ChannelId::new("one").unwrap();
    store.create_channel(&channel, "一").unwrap();
    (directory, paths, store, channel)
}

#[test]
fn image_units_share_budget_without_inventing_tokens_and_unknown_is_held() {
    let (_temporary, _paths, mut store, channel) = fixture();
    let token = request(&channel, "tokens");
    store.reserve_ai_cost(&token).unwrap();
    store
        .settle_ai_cost(
            &channel,
            "tokens",
            &AiCostSettlement::Succeeded {
                actual_cost_micros: 10,
                input_tokens: 10,
                output_tokens: 10,
            },
        )
        .unwrap();
    let mut image = request(&channel, "image");
    image.max_input_tokens = 0;
    image.max_output_tokens = 0;
    image.daily_token_budget = 0;
    image.max_cost_micros = Some(60);
    assert!(store.reserve_ai_cost(&image).is_err());
    assert_eq!(
        store.reserve_ai_image_cost(&image, 1).unwrap().max_images,
        Some(1)
    );
    assert!(store
        .settle_ai_cost(
            &channel,
            "image",
            &AiCostSettlement::Succeeded {
                actual_cost_micros: 5,
                input_tokens: 0,
                output_tokens: 0
            }
        )
        .is_err());
    store
        .settle_ai_cost(
            &channel,
            "image",
            &AiCostSettlement::Unknown {
                error_code: "E-AI-TIMEOUT".into(),
            },
        )
        .unwrap();
    let totals = store.ai_cost_totals(&channel, &image.day).unwrap();
    assert_eq!(
        (
            totals.held_images,
            totals.held_tokens,
            totals.held_micros,
            totals.input_tokens
        ),
        (1, 0, 60, 10)
    );
    let mut another = image.clone();
    another.request_id = "second-image".into();
    assert!(store.reserve_ai_image_cost(&another, 1).is_err());
    let settled = AiCostSettlement::ImagesSucceeded {
        actual_cost_micros: 20,
        images: 1,
    };
    store.settle_ai_cost(&channel, "image", &settled).unwrap();
    store.settle_ai_cost(&channel, "image", &settled).unwrap();
    let totals = store.ai_cost_totals(&channel, &image.day).unwrap();
    assert_eq!(
        (totals.charged_micros, totals.images, totals.held_images),
        (30, 1, 0)
    );
}
#[test]
fn image_overrun_is_saved_before_error_and_units_cannot_be_mixed() {
    let (_temporary, _paths, mut store, channel) = fixture();
    let mut image = request(&channel, "image");
    image.max_input_tokens = 0;
    image.max_output_tokens = 0;
    store.reserve_ai_image_cost(&image, 1).unwrap();
    assert_eq!(
        store
            .settle_ai_cost(
                &channel,
                "image",
                &AiCostSettlement::ImagesSucceeded {
                    actual_cost_micros: 80,
                    images: 2
                }
            )
            .unwrap_err()
            .code,
        "E-AI-USAGE"
    );
    let totals = store.ai_cost_totals(&channel, &image.day).unwrap();
    assert_eq!((totals.charged_micros, totals.images), (80, 2));
    let invalid = request(&channel, "invalid");
    assert!(store.reserve_ai_image_cost(&invalid, 1).is_err());
}

#[test]
fn reservation_then_usage_is_shared_with_totals_and_same_settlement_is_idempotent() {
    let (_temporary, _paths, mut store, channel) = fixture();
    let request = request(&channel, "first");
    store.reserve_ai_cost(&request).unwrap();
    let totals = store.ai_cost_totals(&channel, &request.day).unwrap();
    assert_eq!(totals.held_micros, 60);
    assert_eq!(totals.held_tokens, 100);
    let settled = AiCostSettlement::Succeeded {
        actual_cost_micros: 20,
        input_tokens: 10,
        output_tokens: 15,
    };
    let first = store.settle_ai_cost(&channel, "first", &settled).unwrap();
    assert_eq!(
        store.settle_ai_cost(&channel, "first", &settled).unwrap(),
        first
    );
    let totals = store.ai_cost_totals(&channel, &request.day).unwrap();
    assert_eq!(
        totals,
        AiCostTotals {
            charged_micros: 20,
            input_tokens: 10,
            output_tokens: 15,
            ..Default::default()
        }
    );
    assert_eq!(
        store.reserve_ai_cost(&request).unwrap_err().code,
        "E-AI-RESERVATION"
    );
    let different = AiCostSettlement::Succeeded {
        actual_cost_micros: 21,
        input_tokens: 10,
        output_tokens: 15,
    };
    assert_eq!(
        store
            .settle_ai_cost(&channel, "first", &different)
            .unwrap_err()
            .code,
        "E-AI-RESERVATION"
    );
    assert_eq!(
        store.ai_cost_totals(&channel, &request.day).unwrap(),
        totals
    );
}

#[test]
fn unknown_delivery_holds_money_and_tokens_after_reopen_until_verified_usage() {
    let (_temporary, paths, mut store, channel) = fixture();
    let first = request(&channel, "uncertain");
    store.reserve_ai_cost(&first).unwrap();
    let unknown = AiCostSettlement::Unknown {
        error_code: "E-AI-USAGE".into(),
    };
    let result = store
        .settle_ai_cost(&channel, "uncertain", &unknown)
        .unwrap();
    assert_eq!(result.state, AiCostState::Unknown);
    assert_eq!(
        store
            .settle_ai_cost(&channel, "uncertain", &unknown)
            .unwrap(),
        result
    );
    drop(store);
    let mut store = Store::open(&paths, crate::tests::options()).unwrap();
    let totals = store.ai_cost_totals(&channel, &first.day).unwrap();
    assert_eq!(totals.held_micros, 60);
    assert_eq!(totals.held_tokens, 100);
    assert_eq!(
        store
            .reserve_ai_cost(&request(&channel, "second"))
            .unwrap_err()
            .code,
        "E-AI-BUDGET"
    );
    store
        .settle_ai_cost(
            &channel,
            "uncertain",
            &AiCostSettlement::Succeeded {
                actual_cost_micros: 20,
                input_tokens: 10,
                output_tokens: 20,
            },
        )
        .unwrap();
    assert_eq!(
        store
            .ai_cost_totals(&channel, &first.day)
            .unwrap()
            .held_micros,
        0
    );
    store.reserve_ai_cost(&request(&channel, "second")).unwrap();
}

#[test]
fn confirmed_no_charge_releases_but_billable_failure_without_usage_does_not() {
    let (_temporary, _paths, mut store, channel) = fixture();
    let first = request(&channel, "first");
    store.reserve_ai_cost(&first).unwrap();
    assert_eq!(
        store
            .settle_ai_cost(
                &channel,
                "first",
                &AiCostSettlement::Failed {
                    actual_cost_micros: 1,
                    error_code: "E-AI-USAGE".into()
                }
            )
            .unwrap_err()
            .code,
        "E-AI-USAGE"
    );
    assert_eq!(
        store
            .ai_cost_totals(&channel, &first.day)
            .unwrap()
            .held_micros,
        60
    );
    let failure = AiCostSettlement::Failed {
        actual_cost_micros: 0,
        error_code: "E-AI-USAGE".into(),
    };
    store.settle_ai_cost(&channel, "first", &failure).unwrap();
    store.settle_ai_cost(&channel, "first", &failure).unwrap();
    assert_eq!(
        store.ai_cost_totals(&channel, &first.day).unwrap(),
        AiCostTotals::default()
    );
    assert!(store
        .settle_ai_cost(
            &channel,
            "first",
            &AiCostSettlement::Unknown {
                error_code: "E-AI-USAGE".into()
            }
        )
        .is_err());
}

#[test]
fn concurrent_connections_cannot_exceed_money_or_token_reservations() {
    for (money, tokens) in [(100, 1000), (100_000, 150)] {
        let (_temporary, paths, store, channel) = fixture();
        let barrier = Arc::new(Barrier::new(2));
        let threads: Vec<_> = ["first", "second"]
            .into_iter()
            .map(|id| {
                let paths = paths.clone();
                let barrier = Arc::clone(&barrier);
                let mut reservation = request(&channel, id);
                reservation.daily_budget_micros = money;
                reservation.daily_token_budget = tokens;
                std::thread::spawn(move || {
                    let mut store = Store::open(&paths, crate::tests::options()).unwrap();
                    barrier.wait();
                    store.reserve_ai_cost(&reservation)
                })
            })
            .collect();
        let results: Vec<_> = threads
            .into_iter()
            .map(|thread| thread.join().unwrap())
            .collect();
        assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
        assert_eq!(
            results
                .into_iter()
                .filter_map(|result| result.err())
                .map(|error| error.code)
                .collect::<Vec<_>>(),
            vec!["E-AI-BUDGET"]
        );
        let totals = store
            .ai_cost_totals(&channel, &UtcDay::parse("2026-10-16").unwrap())
            .unwrap();
        assert_eq!(totals.held_micros, 60);
        assert_eq!(totals.held_tokens, 100);
    }
}

#[test]
fn utc_day_and_channel_scope_cannot_settle_another_request() {
    let (_temporary, _paths, mut store, one) = fixture();
    let two = ChannelId::new("two").unwrap();
    store.create_channel(&two, "二").unwrap();
    let first = request(&one, "request");
    store.reserve_ai_cost(&first).unwrap();
    let done = AiCostSettlement::Succeeded {
        actual_cost_micros: 10,
        input_tokens: 1,
        output_tokens: 2,
    };
    assert_eq!(
        store
            .settle_ai_cost(&two, "request", &done)
            .unwrap_err()
            .code,
        "E-AI-RESERVATION"
    );
    assert_eq!(
        store
            .settle_ai_cost(&one, "other-request", &done)
            .unwrap_err()
            .code,
        "E-AI-RESERVATION"
    );
    let mut other_day = request(&one, "tomorrow");
    other_day.at = Timestamp::parse("2026-10-17T00:00:00Z").unwrap();
    other_day.day = UtcDay::from_timestamp(&other_day.at);
    store.reserve_ai_cost(&other_day).unwrap();
    store.reserve_ai_cost(&request(&two, "request")).unwrap();
    store.settle_ai_cost(&two, "request", &done).unwrap();
    assert_eq!(
        store.ai_cost_totals(&one, &first.day).unwrap().held_micros,
        60
    );
    assert_eq!(
        store
            .ai_cost_totals(&two, &first.day)
            .unwrap()
            .charged_micros,
        10
    );
    assert_eq!(
        UtcDay::from_timestamp(&Timestamp::parse("2026-10-16T00:30:00+09:00").unwrap()).as_str(),
        "2026-10-15"
    );
    for invalid in ["2026-02-30", "2026-1-01", "2026-10-16T00:00:00Z"] {
        assert!(UtcDay::parse(invalid).is_err());
    }
}

#[test]
fn unknown_limits_overflow_and_wrong_day_do_not_create_reservations() {
    let (_temporary, _paths, mut store, channel) = fixture();
    let mut invalid = request(&channel, "invalid");
    invalid.max_cost_micros = None;
    assert_eq!(
        store.reserve_ai_cost(&invalid).unwrap_err().code,
        "E-AI-BUDGET"
    );
    invalid.max_cost_micros = Some(u64::MAX);
    assert!(store.reserve_ai_cost(&invalid).is_err());
    invalid.max_cost_micros = Some(0);
    invalid.max_input_tokens = u64::MAX;
    assert!(store.reserve_ai_cost(&invalid).is_err());
    invalid.max_input_tokens = 50;
    invalid.day = UtcDay::parse("2026-10-17").unwrap();
    assert!(store.reserve_ai_cost(&invalid).is_err());
    assert_eq!(
        store
            .repository(&channel)
            .unwrap()
            .list::<CostLedger>()
            .unwrap()
            .len(),
        0
    );
}

#[test]
fn unknown_legacy_prices_block_and_known_ledger_costs_share_the_budget() {
    let (_temporary, _paths, mut store, channel) = fixture();
    let first = request(&channel, "first");
    let mut legacy = CostLedger {
        channel_id: channel.clone(),
        id: "legacy".into(),
        project_id: None,
        job_id: None,
        provider: "legacy".into(),
        model: "legacy".into(),
        units_json: serde_json::json!({"legacy":true}),
        cost_micros: None,
        at: first.at.clone(),
    };
    store.repository(&channel).unwrap().save(&legacy).unwrap();
    assert_eq!(
        store
            .ai_cost_totals(&channel, &first.day)
            .unwrap()
            .unpriced_entries,
        1
    );
    assert_eq!(
        store.reserve_ai_cost(&first).unwrap_err().code,
        "E-AI-BUDGET"
    );
    legacy.cost_micros = Some(50);
    store.repository(&channel).unwrap().save(&legacy).unwrap();
    assert_eq!(
        store.reserve_ai_cost(&first).unwrap_err().code,
        "E-AI-BUDGET"
    );
}

#[test]
fn actual_usage_over_ceiling_is_recorded_before_returning_failure() {
    let (_temporary, _paths, mut store, channel) = fixture();
    let first = request(&channel, "first");
    store.reserve_ai_cost(&first).unwrap();
    let result = store.settle_ai_cost(
        &channel,
        "first",
        &AiCostSettlement::Succeeded {
            actual_cost_micros: 80,
            input_tokens: 60,
            output_tokens: 20,
        },
    );
    assert_eq!(result.unwrap_err().code, "E-AI-USAGE");
    let totals = store.ai_cost_totals(&channel, &first.day).unwrap();
    assert_eq!(totals.charged_micros, 80);
    assert_eq!(totals.input_tokens, 60);
    assert_eq!(totals.held_micros, 0);
    assert_eq!(
        store
            .reserve_ai_cost(&request(&channel, "second"))
            .unwrap_err()
            .code,
        "E-AI-BUDGET"
    );
}

#[test]
fn archiving_during_delivery_blocks_new_reservations_but_retains_actual_accounting() {
    let (_temporary, _paths, mut store, channel) = fixture();
    let first = request(&channel, "first");
    store.reserve_ai_cost(&first).unwrap();
    store.delete_channel(&channel).unwrap();
    assert_eq!(
        store
            .reserve_ai_cost(&request(&channel, "second"))
            .unwrap_err()
            .code,
        "E-STORE-CHANNEL"
    );
    store
        .settle_ai_cost(
            &channel,
            "first",
            &AiCostSettlement::Succeeded {
                actual_cost_micros: 20,
                input_tokens: 10,
                output_tokens: 15,
            },
        )
        .unwrap();
    assert_eq!(
        store
            .ai_cost_totals(&channel, &first.day)
            .unwrap()
            .charged_micros,
        20
    );
    assert!(store.repository(&channel).is_err());
}
