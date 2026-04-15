export interface TimingEntry {
  text: string;
  start: number;  // seconds
  end: number;    // seconds
}

export interface NewsItem {
  hook: string;
  title: string;
  script: string;
  source: string;
  screenshot: string;   // absolute file path or URL
  audio: string;        // absolute file path
  timing: TimingEntry[] | null;
  duration: number;     // seconds (length of audio)
}

export interface NewsVideoProps extends Record<string, unknown> {
  date: string;
  items: NewsItem[];
}
