// Generates src/content/docs/providers/*.md from the gateway catalog —
// the same models.json files the billing engine prices from. Docs cannot
// drift from what customers are charged. Runs as part of `npm run build`.
import { readdirSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const providersDir = join(here, '../../gateway/speechrouter_gateway/providers');
const outDir = join(here, '../src/content/docs/providers');
mkdirSync(outDir, { recursive: true });

const NAMES = {
  deepgram: 'Deepgram', soniox: 'Soniox', assemblyai: 'AssemblyAI',
  openai: 'OpenAI', speechmatics: 'Speechmatics', azure: 'Azure',
  aws: 'AWS', google: 'Google', groq: 'Groq', mistral: 'Mistral',
  elevenlabs: 'ElevenLabs', cartesia: 'Cartesia',
};

const BLURBS = {
  deepgram: 'The realtime workhorse — fast, cheap, excellent English.',
  soniox: '60+ languages with translation-grade accuracy; realtime bills wall-clock session time.',
  assemblyai: 'Streaming turn model built for voice agents, plus strong async models.',
  openai: 'Whisper and the GPT-4o transcribe family — LLM-grade accuracy.',
  speechmatics: 'Broad language coverage; Melia-1 code-switches across 56 languages.',
  azure: 'Azure AI Speech — enterprise realtime + fast transcription.',
  aws: 'Amazon Transcribe streaming with per-request minimums.',
  google: 'Google Cloud Speech-to-Text (Chirp).',
  groq: 'Whisper on LPUs — the fastest batch Whisper anywhere.',
  mistral: 'Voxtral — open-weights transcription via Mistral\'s API.',
  elevenlabs: 'Scribe — high-accuracy STT from the voice company.',
  cartesia: 'Ink — low-latency STT built for realtime agents.',
};

const price = (p) => {
  if (!p) return '—';
  if (p.per_audio_second_usd != null) return `$${p.per_audio_second_usd}/sec`;
  if (p.per_audio_minute_usd != null) return `$${p.per_audio_minute_usd}/min`;
  if (p.per_audio_hour_usd != null) return `$${p.per_audio_hour_usd}/hr`;
  if (p.per_session_hour_usd != null) return `$${p.per_session_hour_usd}/session-hr`;
  return '—';
};

const yes = '<span class="sr-yes">✓</span>', no = '<span class="sr-no">—</span>';

const sample = (models) => {
  const batch = models.find((m) => (m.modes ?? []).includes('batch'));
  if (batch) return `\`\`\`bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \\
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \\
  -F model=${batch.slug} \\
  -F file=@audio.wav
\`\`\``;
  const stream = models[0];
  return `\`\`\`text
wss://api.speechrouter.ai/v1/listen?model=${stream.slug}
\`\`\`
Streaming-only — connect with the [SDKs](/sdks/javascript/) or see [Streaming](/guides/streaming/).`;
};
const providers = readdirSync(providersDir, { withFileTypes: true })
  .filter((d) => d.isDirectory() && !d.name.startsWith('_'))
  .map((d) => d.name)
  .filter((name) => {
    try { readFileSync(join(providersDir, name, 'models.json')); return true; }
    catch { return false; }
  })
  .sort((a, b) => (a === 'soniox' ? -1 : b === 'soniox' ? 1 : a.localeCompare(b)));

let total = 0;
const allSlugs = [];
for (const name of providers) {
  const models = JSON.parse(readFileSync(join(providersDir, name, 'models.json'), 'utf8'))
    .filter((m) => m.kind === 'stt');
  if (!models.length) continue;
  total += models.length;
  allSlugs.push(...models.map((m) => m.slug));

  const rows = models.map((m) => {
    const c = m.capabilities ?? {};
    const min = m.pricing?.minimum_usd ? ` (min $${m.pricing.minimum_usd}/req)` : '';
    return `| \`${m.slug}\` | ${(m.modes ?? []).join(' · ')} | ${price(m.pricing)}${min} | ${c.diarization ? yes : no} | ${c.word_timestamps ? yes : no} |`;
  }).join('\n');

  const sessionNote = models.some((m) => m.pricing?.per_session_hour_usd != null)
    ? '\n:::note[Session-time billing]\nModels priced per **session-hour** meter wall-clock connection time — an open socket bills even while silent, exactly as the vendor bills us.\n:::\n'
    : '';

  const order = providers.indexOf(name) + 1;
  writeFileSync(join(outDir, `${name}.md`), `---
title: ${NAMES[name] ?? name}
description: ${BLURBS[name] ?? `${name} models on SpeechRouter.`}
sidebar: { order: ${order} }
---

${BLURBS[name] ?? ''}

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via \`provider_params\`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
${rows}
${sessionNote}
## Try it

${sample(models)}

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
`);
}

writeFileSync(join(outDir, 'index.md'), `---
title: Providers
description: Every provider behind the one API.
sidebar: { order: 0, label: Overview }
---

${providers.length} providers, ${total} models, one schema. Prices below are
vendor list prices — [we add nothing](/guides/pricing/).

${providers.map((p) => `- [${NAMES[p] ?? p}](/providers/${p}/) — ${BLURBS[p] ?? ''}`).join('\n')}

The live, machine-readable version: [\`GET /v1/models\`](/reference/rest/#get-v1models).
`);

mkdirSync(join(here, '../src/data'), { recursive: true });
writeFileSync(join(here, '../src/data/stats.json'),
  JSON.stringify({ providers: providers.length, models: total, slugs: allSlugs }));

console.log(`generated ${providers.length} provider pages, ${total} models`);
