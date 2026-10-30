const form = document.querySelector('#generator-form');
const imageFolder = document.querySelector('#image-folder');
const srtFile = document.querySelector('#srt-file');
const audioFile = document.querySelector('#audio-file');
const applyZoom = document.querySelector('#apply-zoom');
const applySfx = document.querySelector('#apply-sfx');
const imageSummary = document.querySelector('#image-summary');
const srtSummary = document.querySelector('#srt-summary');
const audioSummary = document.querySelector('#audio-summary');
const button = document.querySelector('#generate-button');
const cancelButton = document.querySelector('#cancel-button');
const status = document.querySelector('#status');
const progressPanel = document.querySelector('#progress-panel');
const progressBar = document.querySelector('#progress-bar');
const progressPercent = document.querySelector('#progress-percent');
const progressLabel = document.querySelector('#progress-label');
const progressDetail = document.querySelector('#progress-detail');
const appName = document.querySelector('#app-name');
const appDescription = document.querySelector('#app-description');
const previewEmpty = document.querySelector('#preview-empty');
const videoPreview = document.querySelector('#video-preview');
const previewState = document.querySelector('#preview-state');
const downloadButton = document.querySelector('#download-button');
let activeJobId = null;
let previewUrl = null;
let previewFilename = 'generated_video.mp4';
const supportedImageExtensions = new Set(['.jpg', '.jpeg', '.png', '.webp', '.bmp']);
const apiBaseUrl = (window.APP_API_BASE_URL || '').replace(/\/+$/, '');

function apiUrl(path) {
  return `${apiBaseUrl}${path}`;
}

function getSupportedImages() {
  return [...imageFolder.files].filter((file) => {
    const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
    return supportedImageExtensions.has(extension);
  });
}

async function countSrtCues(file) {
  const text = await file.text();
  const timestampPattern = /\d{2}:\d{2}:\d{2}[,.]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[,.]\d{3}/g;
  return text.match(timestampPattern)?.length || 0;
}

function updatePreviewAspectRatio() {
  const ratio = document.querySelector('input[name="aspect_ratio"]:checked').value;
  const cssRatio = ratio === '9:16' ? '1 / 1' : '16 / 9';
  videoPreview.style.aspectRatio = cssRatio;
  previewEmpty.style.aspectRatio = cssRatio;
}

function naturalFileOrder(left, right) {
  const leftParts = left.name.split(/(\d+)/);
  const rightParts = right.name.split(/(\d+)/);
  for (let index = 0; index < Math.max(leftParts.length, rightParts.length); index += 1) {
    const leftPart = leftParts[index] || '';
    const rightPart = rightParts[index] || '';
    const leftNumber = Number(leftPart);
    const rightNumber = Number(rightPart);
    if (!Number.isNaN(leftNumber) && !Number.isNaN(rightNumber)) {
      if (leftNumber !== rightNumber) return leftNumber - rightNumber;
    } else if (leftPart.toLowerCase() !== rightPart.toLowerCase()) {
      return leftPart.toLowerCase().localeCompare(rightPart.toLowerCase());
    }
  }
  return left.name.localeCompare(right.name);
}

fetch(apiUrl('/api/version'), { cache: 'no-store' })
  .then((response) => response.json())
  .then(({ name, description, version }) => {
    appName.textContent = name;
    appDescription.textContent = description;
    document.title = name;
    document.querySelector('#app-version').textContent = `v${version}`;
  })
  .catch(() => {});

imageFolder.addEventListener('change', () => {
  const count = imageFolder.files.length;
  imageSummary.textContent = count ? `${count} image${count === 1 ? '' : 's'} selected.` : 'Choose a folder. Images are used in alphabetical order.';
});

srtFile.addEventListener('change', () => {
  srtSummary.textContent = srtFile.files[0]?.name || 'Select the SRT file whose cue times control the slideshow.';
});

audioFile.addEventListener('change', () => {
  audioSummary.textContent = audioFile.files[0]?.name || 'Add background music or narration to the generated video.';
});

document.querySelectorAll('input[name="aspect_ratio"]').forEach((input) => {
  input.addEventListener('change', updatePreviewAspectRatio);
});
updatePreviewAspectRatio();

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const selectedImages = getSupportedImages().sort(naturalFileOrder);
  const selectedSrt = srtFile.files[0];
  if (selectedSrt) {
    const cueCount = await countSrtCues(selectedSrt);
    if (cueCount > selectedImages.length) {
      const confirmed = window.confirm(
        `The SRT contains ${cueCount} cues, but only ${selectedImages.length} images were provided. `
        + `Only the ${selectedImages.length} available images will be used. Do you want to continue?`,
      );
      if (!confirmed) {
        status.className = 'status';
        status.textContent = 'Video generation canceled.';
        return;
      }
    }
  }

  button.disabled = true;
  cancelButton.hidden = false;
  cancelButton.disabled = false;
  progressPanel.hidden = false;
  progressBar.style.width = '0%';
  progressPercent.textContent = '0%';
  progressLabel.textContent = 'Preparing...';
  progressDetail.textContent = 'Uploading files...';
  status.className = 'status working';
  status.textContent = 'Rendering video. This can take a moment...';

  const data = new FormData();
  data.append('srt_file', srtFile.files[0]);
  data.append('apply_zoom', applyZoom.checked ? 'true' : 'false');
  data.append('apply_sfx', applySfx.checked ? 'true' : 'false');
  data.append('aspect_ratio', document.querySelector('input[name="aspect_ratio"]:checked').value);
  if (audioFile.files[0]) data.append('audio_file', audioFile.files[0], audioFile.files[0].name);
  selectedImages.forEach((file) => data.append('images', file, file.name));

  try {
    const response = await fetch(apiUrl('/api/generate'), { method: 'POST', body: data, cache: 'no-store' });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || 'Video generation failed.');
    }
    const { job_id: jobId } = await response.json();
    activeJobId = jobId;
    let job;
    do {
      await new Promise((resolve) => setTimeout(resolve, 500));
      const progressResponse = await fetch(apiUrl(`/api/jobs/${jobId}`), { cache: 'no-store' });
      job = await progressResponse.json();
      if (!progressResponse.ok) throw new Error(job.detail || 'Could not read generation progress.');
      progressBar.style.width = `${job.progress}%`;
      progressPercent.textContent = `${job.progress}%`;
      progressLabel.textContent = job.phase || `Rendering image ${job.current_image} of ${job.total_images}`;
      progressDetail.textContent = job.current_filename || (job.state === 'complete' ? 'Video ready.' : 'Please wait...');
      if (job.state === 'error') throw new Error(job.error);
      if (job.state === 'canceled') throw new Error('Generation canceled.');
    } while (job.state !== 'complete');

    const downloadResponse = await fetch(apiUrl(`/api/jobs/${jobId}/download`), { cache: 'no-store' });
    if (!downloadResponse.ok) throw new Error('Video was created but could not be downloaded.');
    const blob = await downloadResponse.blob();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(blob);
    videoPreview.src = previewUrl;
    videoPreview.hidden = false;
    previewEmpty.hidden = true;
    previewFilename = job.output_name || 'generated_video.mp4';
    downloadButton.hidden = false;
    previewState.textContent = 'Ready to play';
    status.className = 'status success';
    status.textContent = 'Video created and loaded in the preview.';
  } catch (error) {
    status.className = 'status error';
    status.textContent = error.message;
    previewState.textContent = 'No video yet';
  } finally {
    activeJobId = null;
    cancelButton.hidden = true;
    button.disabled = false;
  }
});

cancelButton.addEventListener('click', async () => {
  if (!activeJobId) return;
  cancelButton.disabled = true;
  status.textContent = 'Canceling current FFmpeg process...';
  try {
    await fetch(apiUrl(`/api/jobs/${activeJobId}/cancel`), { method: 'POST', cache: 'no-store' });
  } catch {
    status.textContent = 'Could not contact the server to cancel the job.';
    cancelButton.disabled = false;
  }
});

downloadButton.addEventListener('click', () => {
  if (!previewUrl) return;
  const link = document.createElement('a');
  link.href = previewUrl;
  link.download = previewFilename;
  link.click();
});
