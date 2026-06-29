import { Config } from "./config"
import { Env } from "./types"

export async function embed(text: string, env: Env, cfg: Config): Promise<number[]> {
  const resp = await fetch(`${cfg.openai_base_url}embeddings`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${env.OPENAI_API_KEY}`,
    },
    body: JSON.stringify({
      model: cfg.embed_model,
      input: text.slice(0, 8000),
    }),
  })
  if (!resp.ok) {
    const body = await resp.text()
    throw new Error(`Embedding API error ${resp.status}: ${body}`)
  }
  const data = await resp.json() as { data: { embedding: number[] }[] }
  return data.data[0].embedding
}

export async function expandQuery(q: string, env: Env, cfg: Config): Promise<string> {
  if (!cfg.query_expand) {
    console.log(`expandQuery: query_expand disabled, using original: "${q}"`)
    return q
  }

  const safeQ = q.slice(0, 100).replace(/[^\w\s\u4e00-\u9fff，。？！、]/g, "")
  try {
    console.log(`expandQuery: calling chat API model=${cfg.chat_model} base_url=${cfg.openai_base_url}`)
    const resp = await fetch(`${cfg.openai_base_url}chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${env.OPENAI_API_KEY}`,
      },
      body: JSON.stringify({
        model: cfg.chat_model,
        messages: [
          {
            role: "system",
            content: "你是一个搜索词扩展助手。只输出扩展后的词，用逗号分隔，不要解释，不要其他内容。",
          },
          {
            role: "user",
            content: `扩展搜索词（2-3个同义表达）：${safeQ}`,
          },
        ],
        max_tokens: 120,
        temperature: 0.3,
      }),
    })
    if (!resp.ok) {
      const body = await resp.text()
      throw new Error(`Chat API error ${resp.status}: ${body.slice(0, 200)}`)
    }
    const data = await resp.json() as { choices: { message: { content: string } }[] }
    let expanded = data.choices[0].message.content.trim()
    expanded = expanded.replace(/[^\w\s\u4e00-\u9fff，,、]/g, "").slice(0, 200)
    const result = `${q}，${expanded}`
    console.log(`expandQuery: success "${q}" -> "${result}"`)
    return result
  } catch (e) {
    console.error(`expandQuery: FAILED for "${q}": ${e}`)
    return q
  }
}
