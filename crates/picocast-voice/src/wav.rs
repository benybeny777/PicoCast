use crate::failure;
use picocast_core::Result;
use std::time::Duration;

#[derive(Clone, Debug)]
pub struct WavePolicy {
    pub tail_silence: Duration,
    pub silence_threshold: i16,
    pub maximum_bytes: usize,
}

/// PCM 16 bit の音声。本文は Debug に表示しない。
pub struct WaveAudio {
    pub bytes: Vec<u8>,
    pub sample_rate: u32,
    pub channels: u16,
    pub frames: usize,
    pub trailing_silent_frames: usize,
}

impl WaveAudio {
    pub fn duration_seconds(&self) -> f64 {
        self.frames as f64 / f64::from(self.sample_rate)
    }
}

struct Pcm<'a> {
    sample_rate: u32,
    channels: u16,
    data: &'a [u8],
}

fn u16_at(bytes: &[u8], offset: usize) -> Result<u16> {
    let value: [u8; 2] = bytes
        .get(offset..offset + 2)
        .ok_or_else(|| failure("E-VOICE-AUDIO"))?
        .try_into()
        .map_err(|_| failure("E-VOICE-AUDIO"))?;
    Ok(u16::from_le_bytes(value))
}
fn u32_at(bytes: &[u8], offset: usize) -> Result<u32> {
    let value: [u8; 4] = bytes
        .get(offset..offset + 4)
        .ok_or_else(|| failure("E-VOICE-AUDIO"))?
        .try_into()
        .map_err(|_| failure("E-VOICE-AUDIO"))?;
    Ok(u32::from_le_bytes(value))
}

fn parse(bytes: &[u8]) -> Result<Pcm<'_>> {
    if bytes.get(..4) != Some(b"RIFF")
        || bytes.get(8..12) != Some(b"WAVE")
        || u64::from(u32_at(bytes, 4)?) + 8 != bytes.len() as u64
    {
        return Err(failure("E-VOICE-AUDIO"));
    }
    let mut format = None;
    let mut data = None;
    let mut position = 12_usize;
    while position < bytes.len() {
        let size =
            usize::try_from(u32_at(bytes, position + 4)?).map_err(|_| failure("E-VOICE-AUDIO"))?;
        let start = position
            .checked_add(8)
            .ok_or_else(|| failure("E-VOICE-AUDIO"))?;
        let end = start
            .checked_add(size)
            .ok_or_else(|| failure("E-VOICE-AUDIO"))?;
        let chunk = bytes
            .get(start..end)
            .ok_or_else(|| failure("E-VOICE-AUDIO"))?;
        match bytes.get(position..position + 4) {
            Some(b"fmt ") => {
                if format.is_some()
                    || size < 16
                    || u16_at(chunk, 0)? != 1
                    || u16_at(chunk, 14)? != 16
                {
                    return Err(failure("E-VOICE-AUDIO"));
                }
                let channels = u16_at(chunk, 2)?;
                let rate = u32_at(chunk, 4)?;
                let alignment = u16_at(chunk, 12)?;
                if !(1..=2).contains(&channels)
                    || rate == 0
                    || alignment != channels * 2
                    || rate.checked_mul(u32::from(alignment)) != Some(u32_at(chunk, 8)?)
                {
                    return Err(failure("E-VOICE-AUDIO"));
                }
                format = Some((rate, channels));
            }
            Some(b"data") => {
                if data.replace(chunk).is_some() {
                    return Err(failure("E-VOICE-AUDIO"));
                }
            }
            Some(_) => {}
            None => return Err(failure("E-VOICE-AUDIO")),
        }
        position = end
            .checked_add(size % 2)
            .ok_or_else(|| failure("E-VOICE-AUDIO"))?;
        if position > bytes.len() {
            return Err(failure("E-VOICE-AUDIO"));
        }
    }
    let (sample_rate, channels) = format.ok_or_else(|| failure("E-VOICE-AUDIO"))?;
    let data = data.ok_or_else(|| failure("E-VOICE-AUDIO"))?;
    if data.is_empty() || data.len() % usize::from(channels * 2) != 0 {
        return Err(failure("E-VOICE-AUDIO"));
    }
    Ok(Pcm {
        sample_rate,
        channels,
        data,
    })
}

/// エンジンが生成済みの末尾無音を数え、不足分だけ補う。二重に0.5秒を足さない。
pub fn ensure_trailing_silence(bytes: &[u8], policy: &WavePolicy) -> Result<WaveAudio> {
    if policy.tail_silence.is_zero()
        || policy.silence_threshold < 0
        || bytes.len() > policy.maximum_bytes
    {
        return Err(failure("E-VOICE-AUDIO"));
    }
    let pcm = parse(bytes)?;
    let alignment = usize::from(pcm.channels * 2);
    let is_silent = |frame: &[u8]| {
        frame.chunks_exact(2).all(|sample| {
            let value = i16::from_le_bytes([sample[0], sample[1]]);
            i32::from(value).abs() <= i32::from(policy.silence_threshold)
        })
    };
    let silent = pcm
        .data
        .chunks_exact(alignment)
        .rev()
        .take_while(|frame| is_silent(frame))
        .count();
    let frames = pcm.data.len() / alignment;
    if frames == silent {
        return Err(failure("E-VOICE-AUDIO"));
    }
    let required = policy
        .tail_silence
        .as_nanos()
        .checked_mul(u128::from(pcm.sample_rate))
        .ok_or_else(|| failure("E-VOICE-AUDIO"))?
        .div_ceil(1_000_000_000);
    let required = usize::try_from(required).map_err(|_| failure("E-VOICE-AUDIO"))?;
    let padding = required.saturating_sub(silent);
    let data_size = padding
        .checked_mul(alignment)
        .and_then(|value| pcm.data.len().checked_add(value))
        .ok_or_else(|| failure("E-VOICE-AUDIO"))?;
    let total_size = data_size
        .checked_add(44)
        .ok_or_else(|| failure("E-VOICE-AUDIO"))?;
    if total_size > policy.maximum_bytes || data_size > (u32::MAX - 36) as usize {
        return Err(failure("E-VOICE-AUDIO"));
    }
    let mut output = Vec::with_capacity(total_size);
    output.extend_from_slice(b"RIFF");
    output.extend_from_slice(&(data_size as u32 + 36).to_le_bytes());
    output.extend_from_slice(b"WAVEfmt ");
    output.extend_from_slice(&16_u32.to_le_bytes());
    output.extend_from_slice(&1_u16.to_le_bytes());
    output.extend_from_slice(&pcm.channels.to_le_bytes());
    output.extend_from_slice(&pcm.sample_rate.to_le_bytes());
    output.extend_from_slice(&(pcm.sample_rate * u32::from(pcm.channels) * 2).to_le_bytes());
    output.extend_from_slice(&(pcm.channels * 2).to_le_bytes());
    output.extend_from_slice(&16_u16.to_le_bytes());
    output.extend_from_slice(b"data");
    output.extend_from_slice(&(data_size as u32).to_le_bytes());
    output.extend_from_slice(pcm.data);
    output.resize(total_size, 0);
    Ok(WaveAudio {
        bytes: output,
        sample_rate: pcm.sample_rate,
        channels: pcm.channels,
        frames: frames + padding,
        trailing_silent_frames: silent + padding,
    })
}
