import { registerRoot, Composition } from "remotion";
import React from "react";
import { NewsVideo, calcTotalFrames } from "./NewsVideo";
import { NewsVideoProps } from "./types";
import { CalculateMetadataFunction } from "remotion";
import { Thumbnail, ThumbnailProps } from "./Thumbnail";

const FPS = 30;
const WIDTH = 1080;
const HEIGHT = 1920;

// Default placeholder props for Remotion Studio preview
const defaultProps: NewsVideoProps = {
  date: "2026-04-14",
  items: [
    {
      hook: "AI 快訊",
      title: "示範新聞標題",
      script: "這是示範腳本，實際內容由 Python 傳入。",
      source: "AutoVideo",
      screenshot: "",
      audio: "",
      timing: null,
      duration: 10,
    },
  ],
};

const calculateMetadata: CalculateMetadataFunction<NewsVideoProps> = ({
  props,
}) => {
  const totalFrames = calcTotalFrames(props.items);
  return {
    durationInFrames: totalFrames,
    fps: FPS,
    width: WIDTH,
    height: HEIGHT,
  };
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="NewsVideo"
        component={NewsVideo}
        durationInFrames={FPS * 30}   // placeholder; overridden by calculateMetadata
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={defaultProps}
        calculateMetadata={calculateMetadata}
      />
      <Composition
        id="Thumbnail"
        component={Thumbnail}
        durationInFrames={1}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={{
          hook: "AI 快訊",
          title: "範例標題",
          screenshot: "",
        } as ThumbnailProps}
      />
    </>
  );
};

registerRoot(RemotionRoot);
