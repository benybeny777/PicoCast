#![cfg(test)]
#![allow(clippy::unwrap_used, clippy::panic)]
use super::*;

fn template() -> ThumbnailTemplate {
    serde_json::from_str(include_str!("thumbnail_fixture.json")).unwrap()
}

#[test]
fn invalid_geometry_channel_and_readability_are_rejected() {
    let channel = ChannelId::new("fixture").unwrap();
    let mut value = template();
    assert!(value.validate(&channel).is_ok());
    value.text_left = 1000;
    assert!(value.validate(&channel).is_err());
    value = template();
    value.readability.preview_width = 321;
    assert!(value.validate(&channel).is_err());
    assert!(template()
        .validate(&ChannelId::new("other").unwrap())
        .is_err());
}

#[cfg(windows)]
#[test]
fn measured_text_is_preserved_and_quality_failures_hold() {
    use crate::subtitle::FontSource;
    let mut engine = TextLayoutEngine::new(
        &[FontSource {
            path: "C:/Windows/Fonts/YuGothB.ttc".into(),
        }],
        "ja-JP".into(),
    )
    .unwrap();
    let channel = ChannelId::new("fixture").unwrap();
    let value = template();
    let background = RgbaImage::from_fn(640, 360, |x, y| {
        Rgba([(x % 200) as u8, (y % 200) as u8, 80, 255])
    });
    let original = background.clone();
    let ready = match compose(&mut engine, &channel, &value, "月の秘密", &background, None).unwrap()
    {
        CompositionOutcome::Ready(value) => value,
        CompositionOutcome::Hold(reason) => panic!("{reason:?}"),
    };
    assert_eq!(ready.metrics.text, "月の秘密");
    assert_eq!(ready.metrics.overflowing_pixels, 0);
    assert!(ready.metrics.contrast_passing_fraction >= 0.9);
    assert!(ready
        .metrics
        .line_heights_px
        .iter()
        .all(|height| *height >= 20));
    assert_eq!(ready.preview.dimensions(), (320, 180));
    assert_eq!(
        image::load_from_memory(&ready.png().unwrap())
            .unwrap()
            .to_rgba8(),
        ready.image
    );
    assert_eq!(background, original);
    let mut bad = value.clone();
    bad.readability.minimum_glyph_height_px = 100;
    assert!(
        matches!(compose(&mut engine,&channel,&bad,"月の秘密",&background,None).unwrap(),CompositionOutcome::Hold(issues) if issues==vec![ThumbnailIssue::TextTooSmall])
    );
    bad = value.clone();
    bad.layout.style.normal_rgba = [0, 0, 0, 255];
    assert!(
        matches!(compose(&mut engine,&channel,&bad,"月の秘密",&background,None).unwrap(),CompositionOutcome::Hold(issues) if issues==vec![ThumbnailIssue::LowContrast])
    );
    bad = value.clone();
    bad.layout.max_lines_per_cue = 1;
    bad.layout.max_graphemes_per_line = 4;
    assert!(matches!(
        compose(
            &mut engine,
            &channel,
            &bad,
            "月の秘密と太陽の仕組みを調べよう",
            &background,
            None
        )
        .unwrap(),
        CompositionOutcome::Hold(_)
    ));
    let mut transparent = background.clone();
    transparent.get_pixel_mut(0, 0)[3] = 0;
    assert!(compose(
        &mut engine,
        &channel,
        &value,
        "月の秘密",
        &transparent,
        None
    )
    .is_err());
}
