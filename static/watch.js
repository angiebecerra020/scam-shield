/*
  watch.js — Puts our YouTube video on the video page (watch.html).

  How it fits in: watch.html has a "Video coming soon" card inside
  <div id="video-frame" data-video-id="">. Once someone puts the YouTube
  video's ID in data-video-id, this file swaps the card for the video.
  With no ID, it leaves the card alone.

  We use youtube-nocookie.com, YouTube's privacy mode: YouTube doesn't set
  tracking cookies until someone presses play. That matches our privacy page
  ("no tracking").
*/

// A YouTube video ID is 11 letters, numbers, - or _. Anything else is a typo,
// and we'd rather keep the "coming soon" card than show a broken video.
const YOUTUBE_ID = /^[A-Za-z0-9_-]{11}$/;

/**
 * Show the YouTube video, if watch.html has its ID.
 *
 * Input:  nothing (it reads data-video-id on #video-frame)
 * Output: nothing; it updates the page.
 * Example: data-video-id="dQw4w9WgXcQ"  gives you  the video, ready to play
 *          data-video-id=""             gives you  the "Video coming soon" card
 */
function showVideo() {
  const frame = document.getElementById("video-frame");
  const videoId = frame.dataset.videoId.trim();
  if (!YOUTUBE_ID.test(videoId)) {
    return;
  }

  const video = document.createElement("iframe");
  // rel=0: when it ends, only suggest our own videos, not other channels'
  video.src = `https://www.youtube-nocookie.com/embed/${videoId}?rel=0`;
  video.title = t("watch.videoTitle");
  video.allow = "accelerometer; encrypted-media; gyroscope; picture-in-picture; fullscreen";
  video.allowFullscreen = true;
  video.loading = "lazy";
  video.referrerPolicy = "strict-origin-when-cross-origin";
  frame.replaceChildren(video);
  frame.classList.add("has-video");
}

// The video's title is for screen readers, so update it when the language changes.
document.addEventListener("language-switched", () => {
  const video = document.querySelector("#video-frame iframe");
  if (video !== null) {
    video.title = t("watch.videoTitle");
  }
});

showVideo();
