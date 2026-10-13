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
  elevenlabs: 'ElevenLabs', cartesia: 'Cartesia', telnyx: 'Telnyx',
  palabra: 'Palabra', gemini: 'Gemini', meta: 'Meta', xai: 'xAI',
  rime: 'Rime', inworld: 'Inworld', fishaudio: 'Fish Audio', minimax: 'MiniMax', murf: 'Murf',
};

const BLURBS = {
  deepgram: 'The realtime workhorse — fast, cheap, excellent English.',
  soniox: '60+ languages with translation-grade accuracy; realtime bills wall-clock session time.',
  assemblyai: 'Streaming turn model built for voice agents, plus strong async models.',
  openai: 'Whisper and the GPT-4o transcribe family — LLM-grade accuracy.',
  speechmatics: 'Broad language coverage; Melia-1 code-switches across 56 languages.',
  azure: 'Azure AI Speech — enterprise realtime + fast transcription, plus Microsoft\'s own MAI-Transcribe-2 (60 languages, $0.10/hr promo).',
  aws: 'Amazon Transcribe streaming with per-request minimums.',
  google: 'Google Cloud Speech-to-Text (Chirp).',
  groq: 'Whisper on LPUs — the fastest batch Whisper anywhere.',
  mistral: 'Voxtral — open-weights transcription via Mistral\'s API.',
  elevenlabs: 'Scribe — high-accuracy STT from the voice company.',
  cartesia: 'Ink — low-latency STT built for realtime agents.',
  telnyx: 'Whisper Large-v3-Turbo as a live stream — 100 languages, hosted by Telnyx.',
  palabra: 'Realtime ASR at $0.002/min, with live translation available on the same socket.',
  gemini: 'Gemini 3.5 Transcribe Live at $0.30/hr — 85+ languages, custom vocabulary, and a SMART mode that cleans up disfluencies as it goes.',
  meta: 'Muse Voice Transcribe — 25 languages with code-switching, turn detection and speaker labels at $0.18/hr.',
  xai: 'Grok Voice Transcribe 2.0 — word timings, speaker labels and keyterms included; $0.20/hr streaming, $0.10/hr batch.',
  rime: 'Rime TTS — Coda and Mist v3 voices built for conversational agents.',
  inworld: 'Inworld TTS-2 — expressive voices at $15–25 per 1M characters.',
  fishaudio: 'Fish Audio S2 — huge community voice library; billed per UTF-8 byte.',
  minimax: 'MiniMax Speech 2.x — HD and Turbo voices, strong multilingual coverage.',
  murf: 'Murf Falcon 2 — low-latency streaming TTS at $10 per 1M characters.',
};

const esc = (t) => String(t).replace(/\|/g, '\\|');

const paramsSection = (dir) => {
  let spec;
  try { spec = JSON.parse(readFileSync(join(dir, 'params.json'), 'utf8')); }
  catch { return ''; }
  const fwd = spec.forwarding ?? {};
  const fwdBits = Object.entries(fwd).filter(([, v]) => v)
    .map(([mode, how]) => `${mode} → ${how}`);
  const note = spec.note ? `\n:::note\n${spec.note}\n:::\n` : '';
  if (!spec.params?.length) return `\n## Provider options\n${note}`;
  const rows = spec.params.map((p) => {
    const type = p.enum ? p.enum.map((v) => `\`${v}\``).join(' · ') : p.type;
    const dflt = p.default !== undefined ? `\`${JSON.stringify(p.default)}\`` : '—';
    const modes = (p.modes ?? []).join(' · ');
    return `| \`${esc(p.name)}\` | ${esc(type)} | ${dflt} | ${modes} | ${esc(p.doc)} |`;
  }).join('\n');
  return `\n## Provider options

Reach past the unified surface with [\`provider_params\`](/guides/streaming/#query-parameters)
— forwarded ${fwdBits.join('; ')}. Typed in the SDKs as
\`${'{'}provider${'}'}Params\` interfaces (\`providerParams\` option / \`provider_params=\` kwarg).
${note}
| Param | Type | Default | Applies to | What it does |
| --- | --- | --- | --- | --- |
${rows}
`;
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

// TTS + live models price in characters or per-1M tokens by modality
const UNIT_LABELS = {
  per_character_usd: ['char', 1e6, 'per 1M chars'],
  per_utf8_byte_usd: ['byte', 1e6, 'per 1M UTF-8 bytes'],
  per_1m_text_input_tokens_usd: ['text in'],
  per_1m_cached_text_input_tokens_usd: ['cached text in'],
  per_1m_audio_input_tokens_usd: ['audio in'],
  per_1m_cached_audio_input_tokens_usd: ['cached audio in'],
  per_1m_image_input_tokens_usd: ['image in'],
  per_1m_cached_image_input_tokens_usd: ['cached image in'],
  per_1m_text_output_tokens_usd: ['text out'],
  per_1m_audio_output_tokens_usd: ['audio out'],
};
const unitPrice = (p) => Object.entries(UNIT_LABELS)
  .filter(([field]) => p?.[field] != null)
  .map(([field, [label, scale]]) => (scale
    ? `$${+(p[field] * scale).toFixed(4)} ${UNIT_LABELS[field][2]}`
    : `$${p[field]} ${label}`))
  .join(' · ') || '—';

const voiceSection = (all) => {
  const tts = all.filter((m) => m.kind === 'tts');
  const live = all.filter((m) => m.kind === 'live');
  let out = '';
  if (tts.length) {
    out += `
## Text-to-speech

Token prices are per 1M tokens; "+" means any account or library voice id is accepted. [Text-to-speech guide](/guides/tts/).

| Model | List price | Formats | Voices |
| --- | --- | --- | --- |
${tts.map((m) => `| \`${m.slug}\` | ${unitPrice(m.pricing)}${m.pricing_schedule?.length ? ` (from ${m.pricing_schedule[0].effective_from}: ${unitPrice(m.pricing_schedule[0].pricing)})` : ''} | ${(m.capabilities?.formats ?? []).join(', ')} | ${(m.capabilities?.voices ?? []).length}${m.capabilities?.custom_voices ? '+' : ''} |`).join('\n')}
`;
  }
  if (live.length) {
    out += `
## Live voice

Speech-to-speech sessions in the vendor's own protocol (\`${live[0].dialect}\`). Prices
per 1M tokens. [Live voice guide](/guides/live/).

| Model | List price |
| --- | --- |
${live.map((m) => `| \`${m.slug}\`${m.deprecated ? ' (deprecated)' : ''} | ${unitPrice(m.pricing)} |`).join('\n')}
`;
  }
  return out;
};

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
const ttsSample = (all) => {
  const m = all.find((x) => x.kind === 'tts')
  return `\`\`\`bash
curl -s https://api.speechrouter.ai/v1/audio/speech \\
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" -H "Content-Type: application/json" \\
  -d '{"model": "${m.slug}", "input": "Hello from SpeechRouter", "response_format": "wav"}' \\
  --output hello.wav
\`\`\``;
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
  const all = JSON.parse(readFileSync(join(providersDir, name, 'models.json'), 'utf8'));
  const models = all.filter((m) => (m.kind ?? 'stt') === 'stt');
  if (!all.length) continue;
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

${models.length ? `| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
${rows}
` : ''}${sessionNote}${voiceSection(all)}${paramsSection(join(providersDir, name))}
## Try it

${models.length ? sample(models) : ttsSample(all)}

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
