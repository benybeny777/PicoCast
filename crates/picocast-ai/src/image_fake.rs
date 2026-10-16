//! 合成画像の開発用プロバイダ。ImageGatewayはdevelopment明示時だけ受け付ける。
use crate::{
    image::{
        Assessment, ImageCompletion, ImageInput, ImageInspector, ImageProvider, InlineImage,
        ReviewContext,
    },
    Cancellation, FutureResult, ProviderFault, ProviderId, ProviderResult,
};
use picocast_core::{ChannelId, Result};
use picocast_store::Store;
use std::{
    collections::VecDeque,
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
};
pub struct FakeImageProvider {
    channel: ChannelId,
    responses: VecDeque<ProviderResult<ImageCompletion>>,
    pub calls: Arc<AtomicUsize>,
}
impl FakeImageProvider {
    pub fn new(channel: ChannelId, responses: Vec<ProviderResult<ImageCompletion>>) -> Self {
        Self {
            channel,
            responses: responses.into(),
            calls: Arc::new(AtomicUsize::new(0)),
        }
    }
}
impl ImageProvider for FakeImageProvider {
    fn channel_id(&self) -> &ChannelId {
        &self.channel
    }
    fn id(&self) -> ProviderId {
        ProviderId::Fake
    }
    fn generate<'a>(
        &'a mut self,
        _input: ImageInput<'a>,
    ) -> FutureResult<'a, ProviderResult<ImageCompletion>> {
        Box::pin(async move {
            self.calls.fetch_add(1, Ordering::SeqCst);
            self.responses
                .pop_front()
                .ok_or_else(ProviderFault::contract)?
        })
    }
}
pub struct FakeImageInspector {
    responses: VecDeque<Assessment>,
    pub calls: Arc<AtomicUsize>,
}
impl FakeImageInspector {
    pub fn new(responses: Vec<Assessment>) -> Self {
        Self {
            responses: responses.into(),
            calls: Arc::new(AtomicUsize::new(0)),
        }
    }
}
impl ImageInspector for FakeImageInspector {
    fn synthetic(&self) -> bool {
        true
    }
    fn inspect<'a>(
        &'a mut self,
        _store: &'a mut Store,
        _image: &'a InlineImage,
        _context: ReviewContext<'a>,
        cancel: &'a mut Cancellation,
    ) -> FutureResult<'a, Result<Assessment>> {
        Box::pin(async move {
            cancel.check()?;
            self.calls.fetch_add(1, Ordering::SeqCst);
            self.responses
                .pop_front()
                .ok_or_else(|| crate::failure("E-IMAGE-CONTRACT"))
        })
    }
}
