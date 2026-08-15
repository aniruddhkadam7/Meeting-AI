use rubato::{FftFixedIn, Resampler};

/// Downmixes interleaved multi-channel f32 samples to mono, then resamples from
/// `in_rate` to `TARGET_SAMPLE_RATE` using a fixed-input-size FFT resampler.
///
/// PocketSphinx expects 16kHz mono PCM; WASAPI's shared-mode mix format is usually
/// 44.1kHz or 48kHz stereo, so this conversion runs on every captured chunk.
pub struct AudioResampler {
    channels_in: usize,
    in_rate: usize,
    resampler: Option<FftFixedIn<f32>>,
    chunk_size: usize,
    leftover: Vec<f32>,
}

impl AudioResampler {
    pub fn new(in_rate: u32, channels_in: u16) -> Self {
        let out_rate = super::TARGET_SAMPLE_RATE as usize;
        let in_rate = in_rate as usize;
        let chunk_size = 1024;
        let resampler = if in_rate == out_rate {
            None
        } else {
            FftFixedIn::<f32>::new(in_rate, out_rate, chunk_size, 2, 1).ok()
        };
        Self {
            channels_in: channels_in.max(1) as usize,
            in_rate,
            resampler,
            chunk_size,
            leftover: Vec::new(),
        }
    }

    /// `interleaved` is raw interleaved f32 samples at the input sample rate/channel
    /// count. Returns mono f32 samples at `TARGET_SAMPLE_RATE`, may be empty if not
    /// enough input has accumulated yet to fill one resampler chunk.
    pub fn process(&mut self, interleaved: &[f32]) -> Vec<f32> {
        let mono = downmix_to_mono(interleaved, self.channels_in);

        let Some(resampler) = self.resampler.as_mut() else {
            return mono;
        };

        self.leftover.extend_from_slice(&mono);

        let mut output = Vec::new();
        while self.leftover.len() >= self.chunk_size {
            let block: Vec<f32> = self.leftover.drain(..self.chunk_size).collect();
            match resampler.process(&[block], None) {
                Ok(mut out_frames) => {
                    if let Some(channel0) = out_frames.pop() {
                        output.extend(channel0);
                    }
                }
                Err(_) => break,
            }
        }
        output
    }

    pub fn in_rate(&self) -> usize {
        self.in_rate
    }
}

fn downmix_to_mono(interleaved: &[f32], channels: usize) -> Vec<f32> {
    if channels <= 1 {
        return interleaved.to_vec();
    }
    interleaved
        .chunks(channels)
        .map(|frame| frame.iter().sum::<f32>() / channels as f32)
        .collect()
}
