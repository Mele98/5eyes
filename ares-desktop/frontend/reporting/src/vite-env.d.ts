/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_5EYES_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
