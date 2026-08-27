"""Vera guide & agent-protocol text, in every supported language.

Structural field names (REQUEST / CHANGE / REASON / RESULT / STATE, and the
memory-block labels) stay as short fixed English tokens in every language —
they're machine-consistent anchors an agent can rely on regardless of which
language the surrounding prose is in. Only the explanatory prose and
protocol rules are localized.

`render_guide(lang)`   — full onboarding explanation: what Vera is, how to
                          start a session, how to record with it, the agent
                          behavior protocol, available commands.
`render_protocol(lang)`— just the agent behavior protocol (used inside
                          vera_session_start's response, so it's re-stated
                          every session without re-explaining all of Vera).
`render_project_state(state, lang)` — formats VeraStore.get_project_state()
                          as the memory block a new session reads first.
`resolve_lang(text)`   — normalize a code or language name ("de", "German",
                          "Deutsch", "ドイツ語", or a whole phrase containing
                          one) to a supported code.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

SUPPORTED_LANGUAGES: Dict[str, str] = {
    "en": "English",
    "ja": "日本語",
    "zh": "中文",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
    "ko": "한국어",
    "pt": "Português",
    "ru": "Русский",
    "it": "Italiano",
    "ar": "العربية",
    "hi": "हिन्दी",
}

DEFAULT_LANG = "en"

# Accepts a language's own code, its English name, its native name, and (for
# the two languages the feature was explicitly built around) a same-meaning
# word in the OTHER of the two, so "ドイツ語" and "German" both resolve to "de"
# regardless of which language the request itself was phrased in.
_LANG_ALIASES: Dict[str, str] = {}
for _code, _native in SUPPORTED_LANGUAGES.items():
    _LANG_ALIASES[_code] = _code
    _LANG_ALIASES[_native.lower()] = _code
_LANG_ALIASES.update({
    "english": "en",
    "japanese": "ja", "日本語": "ja",
    "chinese": "zh", "mandarin": "zh",
    "spanish": "es", "castellano": "es",
    "french": "fr",
    "german": "de", "deutsch": "de",
    "korean": "ko",
    "portuguese": "pt",
    "russian": "ru",
    "italian": "it",
    "arabic": "ar",
    "hindi": "hi",
    # cross-language names for the two explicitly-named priority languages
    "ドイツ語": "de", "独語": "de",
    "英語": "en", "英语": "en",
    "日本语": "ja",
    "中文": "zh", "汉语": "zh", "漢語": "zh",
    "français": "fr", "francés": "fr",
    "español": "es",
    "한국어": "ko",
    "português": "pt",
    "русский": "ru",
    "italiano": "it",
    "العربية": "ar",
    "हिन्दी": "hi",
})


def _langs_str(lang: str) -> str:
    sep = "、" if lang in ("ja", "zh") else ", "
    return sep.join(f"{code} ({name})" for code, name in SUPPORTED_LANGUAGES.items())


# Fallback substring matching for resolve_lang(), used only when the exact
# alias lookup misses — e.g. the caller passes a whole phrase like "英語で"
# (Japanese "in English", with a trailing particle) or "in English please"
# rather than a clean code/name. Deliberately excludes the bare ISO codes
# ("en", "ja", "it", "hi", ...) and anything under 3 characters: those are
# too short to substring-match safely — "it" or "hi" turn up constantly
# inside unrelated English text ("is it done", "hi there"). Full names in
# any script (English/native) are safe: "german"/"deutsch"/"ドイツ語" don't
# collide with unrelated text the way 2-letter codes do.
_ISO_CODES = set(SUPPORTED_LANGUAGES.keys())
_FUZZY_LANG_CANDIDATES = sorted(
    (alias for alias in _LANG_ALIASES if alias not in _ISO_CODES and len(alias) >= 3),
    key=len, reverse=True,  # longest first, so "japanese" wins over any shorter overlap
)


def resolve_lang(requested: Optional[str]) -> str:
    """Normalize a code, language name, or a whole phrase containing one
    ("英語で", "in English please", "auf Deutsch") to a supported code;
    'auto' or anything unrecognized falls back to DEFAULT_LANG rather than
    erroring — a guide in the wrong-but-known language beats a crash."""
    if not requested:
        return DEFAULT_LANG
    key = requested.strip().lower()
    if key in ("auto", ""):
        return DEFAULT_LANG
    if key in _LANG_ALIASES:
        return _LANG_ALIASES[key]
    for alias in _FUZZY_LANG_CANDIDATES:
        if alias in key:
            return _LANG_ALIASES[alias]
    return DEFAULT_LANG


# ---------------------------------------------------------------------------
# Guide content — tagline / core_idea / start / record / protocol / commands
# ---------------------------------------------------------------------------
# `protocol` is a list of short imperative rules — the actual behavior
# contract, meant to survive being re-shown every single session without
# feeling repetitive to a model reading it.

_GUIDE: Dict[str, Dict[str, Any]] = {
    "en": {
        "tagline": "a shared, append-only, citable memory for AI coding agents.",
        "core_idea": (
            "Sessions end. The project doesn't. Claude, a local model, or any "
            "other MCP-compatible agent can pick up exactly where the last one "
            "left off — Claude → Vera → Local → Vera → Claude — by reading the "
            "same memory instead of your session history. Vera does not "
            "interpret what it stores — no fact extraction, no contradiction "
            "detection. Every entry just gets a citable number (#N); making "
            "sense of it is the agent's job, the same way a person free-reads "
            "a log rather than being handed conclusions."
        ),
        "start": (
            "At the start of a session, call vera_session_start (CLI: "
            "`vera start`) BEFORE doing any work. It returns the latest "
            "compressed digest (if one exists) plus everything recorded "
            "since it — or, if there's no digest yet, the most recent "
            "entries — each with a citation number. Read it before you "
            "touch anything."
        ),
        "record": (
            "When the user says \"Vera\", record the turn with vera_record "
            "(CLI: `vera record`). Distill the conversation into: REQUEST "
            "(what was asked), CHANGE (what you did, and which files), "
            "REASON (why you structured it that way), RESULT (what "
            "happened), STATE (your current understanding). Also say the "
            "STATE part out loud to the user in your reply — Vera never "
            "reads your conversation, only what you explicitly tell it, "
            "and never interprets it either."
        ),
        "protocol": [
            "Before doing any work in a new session, call vera_session_start and read the result.",
            "Before making a significant decision, skim recent entries (and the digest, if any) for what was already decided — don't silently contradict something already on record. Vera won't catch this for you; that judgment is yours.",
            "After a significant change, call vera_record with REQUEST/CHANGE/REASON/RESULT — don't wait until the whole task is done.",
            "Distinguish observation, decision, assumption, and result — never record a guess as if it were a fact.",
            "Never overwrite a past event. Vera's memory is append-only by design; correct forward, don't rewrite history.",
            "When the user says \"Vera\" mid-conversation, that means: save what happened, AND explain your current understanding to the user.",
            "Recognize \"Vera\"/\"vera\" as the trigger in any case and anywhere in the message — \"Vera guide\", \"vera guide\", \"open Vera guide in German\", 「現在のVera guideを見せて」 all count, not just an exact match; if the message names a language, use it for that call, otherwise default to the conversation's current language.",
            "Cite memory by its number when you rely on it (\"per #12\") so the user or a later session can check it exactly with vera lookup. Check vera_stats' size.over_threshold at session start — if true, the uncompressed memory has grown large enough that handing it to a fresh agent risks overflowing its context; read through it, write a digest that cites the numbers it covers, tell the user compression may help, and call vera_compress.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · vera lookup <n> · "
            "vera search <query> · vera compress --text \"...\" · vera stats"
        ),
        "switch": (
            "Ask for the guide in another language and Vera answers in it — "
            "e.g. \"Start Vera guide in German\", or in Japanese: "
            "「Vera guideをドイツ語で起動して」. Supported: {langs}."
        ),
    },
    "ja": {
        "tagline": "AIコーディングエージェントのための、共有・追記専用・引用可能な記憶。",
        "core_idea": (
            "セッションは終わっても、プロジェクトは終わりません。Claude、ローカルモデル、"
            "他のMCP対応エージェントは、あなたのセッション履歴ではなく同じ記憶を"
            "読むことで、直前の作業をそのまま引き継げます — Claude → Vera → Local → Vera → Claude。"
            "Veraは保存内容を解釈しません — 事実抽出も矛盾検出もありません。各エントリには"
            "引用可能な番号（#N）が付くだけで、それをどう解釈するかはエージェント側の仕事です。"
            "人が結論だけを渡されるのではなく、ログを自由に読むのと同じです。"
        ),
        "start": (
            "セッション開始時、作業を始める前に vera_session_start（CLI: `vera start`）"
            "を必ず呼んでください。最新の圧縮ダイジェスト（あれば）とそれ以降に記録された"
            "すべて、ダイジェストがまだ無ければ直近のエントリが、それぞれ引用番号付きで"
            "返されます。何かに触れる前に必ず読んでください。"
        ),
        "record": (
            "ユーザーが「Vera」と言ったら、vera_record（CLI: `vera record`）で"
            "そのやり取りを記録してください。会話を REQUEST（何を求められたか）、"
            "CHANGE（何をしたか、どのファイルか）、REASON（なぜその構造にしたか）、"
            "RESULT（何が起きたか）、STATE（現在どう理解しているか）に整理してください。"
            "STATEの内容は返信の中でユーザーにも説明してください — Veraは会話そのものを"
            "見ておらず、あなたが明示的に伝えたことだけを記録し、それを解釈することもありません。"
        ),
        "protocol": [
            "新しいセッションで作業を始める前に、必ず vera_session_start を呼び、結果を読むこと。",
            "重要な判断をする前に、直近のエントリ（とダイジェストがあればそれ）に目を通し、既に決まっていたことに気づかず反しないこと。これはVeraが代わりにチェックしてくれるものではなく、あなた自身の判断です。",
            "大きな変更のあとは、タスク全体が終わるのを待たず、その都度 vera_record で REQUEST/CHANGE/REASON/RESULT を記録すること。",
            "観察（observation）・決定（decision）・仮定（assumption）・結果（result）を区別すること。推測を事実として記録しないこと。",
            "過去のイベントを絶対に上書きしないこと。Veraの記憶は設計上追記専用。訂正は前進させて記録する（履歴の書き換えはしない）。",
            "会話の途中でユーザーが「Vera」と言ったら、それは『今の作業内容を保存し、現在の理解をユーザーに説明する』という意味。",
            "「Vera」「vera」は大文字小文字を問わず、メッセージ中のどこにあってもトリガーとして認識すること（「Vera guide」「vera guide」「現在のVera guideを見せて」「ドイツ語でVera guideを起動して」すべて該当）。メッセージ内で言語が指定されていればその言語で、指定がなければ会話中の現在の言語をデフォルトにすること。",
            "記憶を根拠に使うときは番号で引用すること（「#12によれば」）。ユーザーや後のセッションが vera lookup で正確に確認できるようにするため。セッション開始時に vera_stats の size.over_threshold を確認し、trueなら未圧縮の記憶が大きくなりすぎて新しいエージェントの文脈を圧迫しかねない状態。中身を読み、対象番号を引用したダイジェストを書き、ユーザーに圧縮を提案した上で vera_compress を呼ぶこと。",
        ],
        "commands": (
            "vera start ・ vera record ・ vera guide [--lang xx] ・ vera lookup <n> ・ "
            "vera search <query> ・ vera compress --text \"...\" ・ vera stats"
        ),
        "switch": (
            "他の言語でガイドを見たいときは、そう伝えるだけで構いません（例:"
            "「ドイツ語でVera guideを起動して」、英語なら \"Start Vera guide in German\"）。"
            "対応言語: {langs}。"
        ),
    },
    "zh": {
        "tagline": "面向AI编程智能体的共享、仅追加、可引用记忆。",
        "core_idea": (
            "会话会结束，项目不会。Claude、本地模型或任何兼容MCP的智能体，都可以通过读取"
            "同一份记忆（而不是你的会话历史）来准确衔接上一次的工作 —— "
            "Claude → Vera → Local → Vera → Claude。Vera不会解释它存的内容——没有事实提取，"
            "也没有矛盾检测。每条记录只会拿到一个可引用的编号（#N），如何理解它是智能体自己的事，"
            "就像人自由阅读日志、而不是被直接告知结论一样。"
        ),
        "start": (
            "会话开始时，在开始任何工作之前先调用 vera_session_start"
            "（CLI：`vera start`）。它会返回最新的压缩摘要（如果有的话）加上此后记录的一切——"
            "如果还没有摘要，就是最近的条目——每条都带有引用编号。动手之前请先读完。"
        ),
        "record": (
            "当用户说“Vera”时，用 vera_record（CLI：`vera record`）记录这次交互。"
            "把对话提炼为：REQUEST（被要求做什么）、CHANGE（做了什么、涉及哪些文件）、"
            "REASON（为什么这样设计）、RESULT（发生了什么）、STATE（你目前的理解）。"
            "STATE部分也要在回复里对用户说出来——Vera不会旁听对话，只记录你明确告诉它的内容，"
            "也不会对其做任何解读。"
        ),
        "protocol": [
            "在新会话中开始任何工作之前，先调用 vera_session_start 并阅读结果。",
            "在做出重要决定之前，浏览最近的条目（以及摘要，如果有的话），了解已经决定过什么——不要在不知情的情况下与已有记录相悖。这不是Vera替你检查的事，而是你自己的判断。",
            "发生重要变更后，立即用 vera_record 记录 REQUEST/CHANGE/REASON/RESULT，不要等到整个任务结束。",
            "区分 observation（观察）、decision（决定）、assumption（假设）、result（结果）—— 不要把猜测当作事实记录。",
            "绝不覆盖过去的记录。Vera的记忆按设计仅可追加；有修正就继续追加新记录，不要改写历史。",
            "对话中用户说“Vera”，意味着：保存刚才发生的事，并向用户说明你目前的理解。",
            "无论大小写，无论出现在消息的哪个位置，都要把“Vera”/“vera”识别为触发词（“Vera guide”“vera guide”“用德语打开Vera guide”“显示当前的Vera guide”均算数），不要求完全匹配；消息中指明了语言就用该语言调用，否则默认使用当前对话所用的语言。",
            "引用记忆时标出编号（“根据#12”），方便用户或之后的会话用 vera lookup 精确核实。会话开始时检查 vera_stats 的 size.over_threshold；为真时说明未压缩的记忆已经大到可能让新智能体的上下文溢出——通读内容，写一份引用相关编号的摘要，告诉用户压缩可能有帮助，然后调用 vera_compress。",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · vera lookup <n> · "
            "vera search <query> · vera compress --text \"...\" · vera stats"
        ),
        "switch": (
            "想用其他语言看指南，直接说出来就行（例如 “Start Vera guide in German”）。"
            "支持的语言：{langs}。"
        ),
    },
    "es": {
        "tagline": "una memoria compartida, de solo anexado y citable para agentes de codificación con IA.",
        "core_idea": (
            "Las sesiones terminan. El proyecto no. Claude, un modelo local o "
            "cualquier otro agente compatible con MCP puede continuar justo donde "
            "quedó el anterior — Claude → Vera → Local → Vera → Claude — leyendo "
            "la misma memoria en lugar de tu historial de sesión. Vera no "
            "interpreta lo que almacena — sin extracción de hechos, sin "
            "detección de contradicciones. Cada entrada solo recibe un número "
            "citable (#N); darle sentido es tarea del agente, igual que una "
            "persona lee un registro libremente en vez de recibir conclusiones."
        ),
        "start": (
            "Al iniciar una sesión, llama a vera_session_start (CLI: `vera "
            "start`) ANTES de hacer nada. Devuelve el último resumen "
            "comprimido (si existe) más todo lo registrado desde entonces "
            "— o, si aún no hay resumen, las entradas más recientes — cada "
            "una con un número de cita. Léelo antes de tocar nada."
        ),
        "record": (
            "Cuando el usuario diga \"Vera\", registra el turno con vera_record "
            "(CLI: `vera record`). Destila la conversación en: REQUEST "
            "(qué se pidió), CHANGE (qué hiciste y en qué archivos), REASON "
            "(por qué lo estructuraste así), RESULT (qué ocurrió), STATE (tu "
            "comprensión actual). Explica también el STATE al usuario en tu "
            "respuesta — Vera nunca lee la conversación, solo lo que le "
            "indicas explícitamente, y tampoco lo interpreta."
        ),
        "protocol": [
            "Antes de trabajar en una sesión nueva, llama a vera_session_start y lee el resultado.",
            "Antes de tomar una decisión importante, revisa las entradas recientes (y el resumen, si existe) para ver qué ya se decidió — no contradigas sin querer algo ya registrado. Vera no te avisará de esto por ti; ese juicio es tuyo.",
            "Tras un cambio importante, llama a vera_record con REQUEST/CHANGE/REASON/RESULT — no esperes a terminar toda la tarea.",
            "Distingue observation, decision, assumption y result — nunca registres una suposición como si fuera un hecho.",
            "Nunca sobrescribas un evento pasado. La memoria de Vera es de solo anexado por diseño; corrige hacia adelante, no reescribas la historia.",
            "Cuando el usuario diga \"Vera\" a mitad de la conversación, significa: guarda lo ocurrido y explica al usuario tu comprensión actual.",
            "Reconoce \"Vera\"/\"vera\" como disparador en cualquier mayúscula/minúscula y en cualquier parte del mensaje (\"Vera guide\", \"vera guide\", \"abre Vera guide en alemán\" cuentan todas), no solo una coincidencia exacta; si el mensaje nombra un idioma, úsalo para esa llamada, si no, usa por defecto el idioma actual de la conversación.",
            "Cita la memoria por su número cuando te bases en ella (\"según #12\") para que el usuario o una sesión posterior pueda verificarlo con vera lookup. Revisa size.over_threshold de vera_stats al iniciar sesión — si es true, la memoria sin comprimir ha crecido lo suficiente como para arriesgar desbordar el contexto de un agente nuevo; léela, escribe un resumen que cite los números que cubre, dile al usuario que comprimir podría ayudar, y llama a vera_compress.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · vera lookup <n> · "
            "vera search <query> · vera compress --text \"...\" · vera stats"
        ),
        "switch": (
            "Pide la guía en otro idioma y Vera responderá en él — p. ej. "
            "\"Start Vera guide in German\". Idiomas admitidos: {langs}."
        ),
    },
    "fr": {
        "tagline": "une mémoire partagée, en ajout seul et citable pour les agents de code IA.",
        "core_idea": (
            "Les sessions se terminent. Pas le projet. Claude, un modèle local "
            "ou tout autre agent compatible MCP peut reprendre exactement là où "
            "le précédent s'est arrêté — Claude → Vera → Local → Vera → Claude "
            "— en lisant la même mémoire plutôt que votre historique de "
            "session. Vera n'interprète pas ce qu'elle stocke — pas "
            "d'extraction de faits, pas de détection de contradictions. "
            "Chaque entrée reçoit juste un numéro citable (#N) ; lui donner "
            "un sens est le travail de l'agent, comme une personne lit "
            "librement un journal plutôt que de recevoir des conclusions."
        ),
        "start": (
            "Au début d'une session, appelez vera_session_start (CLI : `vera "
            "start`) AVANT toute action. Cela renvoie le dernier résumé "
            "compressé (s'il existe) plus tout ce qui a été enregistré "
            "depuis — ou, s'il n'y a pas encore de résumé, les entrées les "
            "plus récentes — chacune avec un numéro de citation. Lisez-le "
            "avant de toucher à quoi que ce soit."
        ),
        "record": (
            "Quand l'utilisateur dit \"Vera\", enregistrez l'échange avec "
            "vera_record (CLI : `vera record`). Distillez la conversation "
            "en : REQUEST (ce qui a été demandé), CHANGE (ce que vous avez "
            "fait, et quels fichiers), REASON (pourquoi cette structure), "
            "RESULT (ce qui s'est passé), STATE (votre compréhension "
            "actuelle). Dites aussi le STATE à voix haute à l'utilisateur "
            "dans votre réponse — Vera ne lit jamais la conversation, "
            "seulement ce que vous lui dites explicitement, et ne "
            "l'interprète pas non plus."
        ),
        "protocol": [
            "Avant tout travail dans une nouvelle session, appelez vera_session_start et lisez le résultat.",
            "Avant une décision importante, parcourez les entrées récentes (et le résumé, s'il existe) pour voir ce qui a déjà été décidé — ne contredisez pas sans le savoir quelque chose déjà enregistré. Vera ne le détectera pas à votre place ; ce jugement vous appartient.",
            "Après un changement important, appelez vera_record avec REQUEST/CHANGE/REASON/RESULT — n'attendez pas la fin de toute la tâche.",
            "Distinguez observation, decision, assumption et result — n'enregistrez jamais une supposition comme un fait.",
            "N'écrasez jamais un événement passé. La mémoire de Vera est en ajout seul par conception ; corrigez en avançant, ne réécrivez pas l'historique.",
            "Quand l'utilisateur dit \"Vera\" en cours de conversation, cela signifie : enregistrez ce qui s'est passé ET expliquez à l'utilisateur votre compréhension actuelle.",
            "Reconnaissez \"Vera\"/\"vera\" comme déclencheur quelle que soit la casse et où qu'il apparaisse dans le message (\"Vera guide\", \"vera guide\", \"ouvre Vera guide en allemand\" comptent toutes), pas seulement une correspondance exacte ; si le message nomme une langue, utilisez-la pour cet appel, sinon utilisez par défaut la langue actuelle de la conversation.",
            "Citez la mémoire par son numéro quand vous vous en servez (\"selon #12\") pour que l'utilisateur ou une session ultérieure puisse vérifier exactement avec vera lookup. Vérifiez size.over_threshold de vera_stats au début de la session — si vrai, la mémoire non compressée a assez grossi pour risquer de déborder le contexte d'un nouvel agent ; lisez-la, écrivez un résumé citant les numéros couverts, dites à l'utilisateur qu'une compression pourrait aider, et appelez vera_compress.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · vera lookup <n> · "
            "vera search <query> · vera compress --text \"...\" · vera stats"
        ),
        "switch": (
            "Demandez le guide dans une autre langue et Vera répondra dans "
            "cette langue — p. ex. \"Start Vera guide in German\". Langues "
            "prises en charge : {langs}."
        ),
    },
    "de": {
        "tagline": "ein geteiltes, nur-anhängendes, zitierbares Gedächtnis für KI-Coding-Agenten.",
        "core_idea": (
            "Sitzungen enden. Das Projekt nicht. Claude, ein lokales Modell "
            "oder jeder andere MCP-kompatible Agent kann genau dort "
            "weitermachen, wo der letzte aufgehört hat — Claude → Vera → "
            "Local → Vera → Claude — indem dasselbe Gedächtnis statt des "
            "Sitzungsverlaufs gelesen wird. Vera interpretiert nicht, was "
            "gespeichert wird — keine Fakten-Extraktion, keine "
            "Widerspruchserkennung. Jeder Eintrag bekommt nur eine "
            "zitierbare Nummer (#N); ihn zu deuten ist Aufgabe des Agenten "
            "— wie jemand, der ein Protokoll frei liest, statt fertige "
            "Schlussfolgerungen zu erhalten."
        ),
        "start": (
            "Rufen Sie zu Beginn einer Sitzung vera_session_start auf (CLI: "
            "`vera start`), BEVOR Sie irgendetwas tun. Es liefert die "
            "neueste komprimierte Zusammenfassung (falls vorhanden) plus "
            "alles, was seither aufgezeichnet wurde — oder, falls es noch "
            "keine gibt, die aktuellsten Einträge — jeweils mit einer "
            "Zitiernummer. Lesen Sie es, bevor Sie irgendetwas anfassen."
        ),
        "record": (
            "Wenn der Nutzer \"Vera\" sagt, protokollieren Sie den Vorgang mit "
            "vera_record (CLI: `vera record`). Destillieren Sie das "
            "Gespräch zu: REQUEST (was verlangt wurde), CHANGE (was Sie "
            "getan haben, welche Dateien), REASON (warum diese Struktur), "
            "RESULT (was passiert ist), STATE (Ihr aktuelles Verständnis). "
            "Sprechen Sie den STATE-Teil auch in Ihrer Antwort an den "
            "Nutzer aus — Vera liest niemals das Gespräch selbst, nur was "
            "Sie ihm ausdrücklich mitteilen, und interpretiert es auch nicht."
        ),
        "protocol": [
            "Rufen Sie vor jeder Arbeit in einer neuen Sitzung vera_session_start auf und lesen Sie das Ergebnis.",
            "Sehen Sie sich vor einer wichtigen Entscheidung die aktuellen Einträge (und die Zusammenfassung, falls vorhanden) an, um zu prüfen, was bereits entschieden wurde — widersprechen Sie nicht unbemerkt etwas bereits Festgehaltenem. Vera prüft das nicht für Sie; dieses Urteil liegt bei Ihnen.",
            "Rufen Sie nach einer wesentlichen Änderung vera_record mit REQUEST/CHANGE/REASON/RESULT auf — warten Sie nicht, bis die ganze Aufgabe fertig ist.",
            "Unterscheiden Sie observation, decision, assumption und result — protokollieren Sie niemals eine Vermutung als Tatsache.",
            "Überschreiben Sie niemals ein vergangenes Ereignis. Veras Gedächtnis ist per Design nur-anhängend; korrigieren Sie vorwärts, statt Geschichte umzuschreiben.",
            "Wenn der Nutzer mitten im Gespräch \"Vera\" sagt, bedeutet das: Speichern Sie, was passiert ist, UND erklären Sie dem Nutzer Ihr aktuelles Verständnis.",
            "Erkennen Sie \"Vera\"/\"vera\" unabhängig von Groß-/Kleinschreibung und Position in der Nachricht als Auslöser (\"Vera guide\", \"vera guide\", \"Vera guide auf Deutsch öffnen\" zählen alle), nicht nur bei exakter Übereinstimmung; nennt die Nachricht eine Sprache, verwenden Sie diese für den Aufruf, andernfalls die aktuelle Sprache des Gesprächs.",
            "Zitieren Sie das Gedächtnis mit seiner Nummer, wenn Sie sich darauf stützen (\"laut #12\"), damit der Nutzer oder eine spätere Sitzung es mit vera lookup genau prüfen kann. Prüfen Sie size.over_threshold von vera_stats zu Sitzungsbeginn — ist es wahr, ist das unkomprimierte Gedächtnis groß genug geworden, dass es den Kontext eines neuen Agenten sprengen könnte; lesen Sie es durch, schreiben Sie eine Zusammenfassung, die die abgedeckten Nummern zitiert, sagen Sie dem Nutzer, dass Komprimieren helfen könnte, und rufen Sie vera_compress auf.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · vera lookup <n> · "
            "vera search <query> · vera compress --text \"...\" · vera stats"
        ),
        "switch": (
            "Fragen Sie nach dem Guide in einer anderen Sprache, und Vera "
            "antwortet darin — z. B. \"Vera guide auf Deutsch starten\". "
            "Unterstützt: {langs}."
        ),
    },
    "ko": {
        "tagline": "AI 코딩 에이전트를 위한 공유형, 추가 전용, 인용 가능한 기억.",
        "core_idea": (
            "세션은 끝나지만 프로젝트는 끝나지 않습니다. Claude, 로컬 모델, 또는 다른 "
            "MCP 호환 에이전트는 세션 기록이 아니라 동일한 기억을 읽음으로써 "
            "이전 작업을 정확히 이어받을 수 있습니다 — Claude → Vera → Local → Vera → Claude. "
            "Vera는 저장한 내용을 해석하지 않습니다 — 사실 추출도, 모순 감지도 없습니다. "
            "각 항목은 그저 인용 가능한 번호(#N)를 부여받을 뿐이며, 그것을 어떻게 해석할지는 "
            "에이전트의 몫입니다. 사람이 결론만 전달받는 대신 로그를 자유롭게 읽는 것과 같습니다."
        ),
        "start": (
            "세션을 시작할 때는 작업을 하기 전에 반드시 vera_session_start"
            "(CLI: `vera start`)를 호출하세요. 최신 압축 다이제스트(있다면)와 그 이후에 "
            "기록된 모든 것 — 다이제스트가 아직 없다면 최근 항목들 — 이 각각 인용 번호와 "
            "함께 반환됩니다. 무엇이든 손대기 전에 반드시 읽으세요."
        ),
        "record": (
            "사용자가 \"Vera\"라고 말하면 vera_record(CLI: `vera record`)로 "
            "그 내용을 기록하세요. 대화를 REQUEST(무엇을 요청받았는지), CHANGE(무엇을 "
            "했는지, 어떤 파일인지), REASON(왜 그렇게 구성했는지), RESULT(무슨 일이 "
            "일어났는지), STATE(현재 이해)로 정리하세요. STATE 내용은 답변에서 사용자에게도 "
            "설명하세요 — Vera는 대화를 직접 보지 않고, 당신이 명시적으로 알려준 것만 "
            "기록하며, 그것을 해석하지도 않습니다."
        ),
        "protocol": [
            "새 세션에서 작업을 시작하기 전에 반드시 vera_session_start를 호출하고 결과를 읽을 것.",
            "중요한 결정을 내리기 전에 최근 항목(과 있다면 다이제스트)을 훑어보고 이미 결정된 것을 확인할 것 — 이미 기록된 것과 모르고 모순되지 않도록. 이는 Vera가 대신 잡아주는 것이 아니라 당신 자신의 판단입니다.",
            "중요한 변경 후에는 전체 작업이 끝날 때까지 기다리지 말고 그때그때 vera_record로 REQUEST/CHANGE/REASON/RESULT를 기록할 것.",
            "observation(관찰)·decision(결정)·assumption(가정)·result(결과)를 구분할 것 — 추측을 사실처럼 기록하지 말 것.",
            "과거 이벤트를 절대 덮어쓰지 말 것. Vera의 기억은 설계상 추가 전용이며, 정정은 앞으로 나아가며 기록하는 것이지 역사를 다시 쓰는 것이 아님.",
            "대화 중 사용자가 \"Vera\"라고 말하면, 그것은 '지금까지의 작업을 저장하고 현재 이해를 사용자에게 설명하라'는 뜻.",
            "\"Vera\"/\"vera\"는 대소문자나 메시지 내 위치와 무관하게 트리거로 인식할 것(\"Vera guide\", \"vera guide\", \"독일어로 Vera guide 열어줘\" 모두 해당) — 정확히 일치할 때만이 아님. 메시지에 언어가 명시되어 있으면 그 언어를 사용하고, 없으면 현재 대화 언어를 기본값으로 할 것.",
            "기억에 근거할 때는 번호로 인용할 것(\"#12에 따르면\") — 사용자나 이후 세션이 vera lookup으로 정확히 확인할 수 있도록. 세션 시작 시 vera_stats의 size.over_threshold를 확인할 것 — true라면 압축되지 않은 기억이 커져서 새 에이전트의 컨텍스트를 넘칠 위험이 있다는 뜻이니, 내용을 읽고 대상 번호를 인용한 다이제스트를 작성해 사용자에게 압축을 제안한 뒤 vera_compress를 호출할 것.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · vera lookup <n> · "
            "vera search <query> · vera compress --text \"...\" · vera stats"
        ),
        "switch": (
            "다른 언어로 가이드를 보고 싶다면 그렇게 요청하면 됩니다 (예: "
            "\"Start Vera guide in German\"). 지원 언어: {langs}."
        ),
    },
    "pt": {
        "tagline": "uma memória compartilhada, somente de acréscimo e citável para agentes de código com IA.",
        "core_idea": (
            "As sessões terminam. O projeto não. Claude, um modelo local ou "
            "qualquer outro agente compatível com MCP pode continuar exatamente "
            "de onde o anterior parou — Claude → Vera → Local → Vera → Claude "
            "— lendo a mesma memória em vez do seu histórico de sessão. O "
            "Vera não interpreta o que armazena — sem extração de fatos, sem "
            "detecção de contradições. Cada entrada só recebe um número "
            "citável (#N); dar sentido a isso é tarefa do agente, assim como "
            "uma pessoa lê um registro livremente em vez de receber conclusões."
        ),
        "start": (
            "No início de uma sessão, chame vera_session_start (CLI: `vera "
            "start`) ANTES de fazer qualquer coisa. Isso retorna o último "
            "resumo compactado (se existir) mais tudo registrado desde "
            "então — ou, se ainda não houver resumo, as entradas mais "
            "recentes — cada uma com um número de citação. Leia antes de "
            "tocar em qualquer coisa."
        ),
        "record": (
            "Quando o usuário disser \"Vera\", registre o turno com vera_record "
            "(CLI: `vera record`). Resuma a conversa em: REQUEST (o "
            "que foi pedido), CHANGE (o que você fez, e quais arquivos), "
            "REASON (por que estruturou assim), RESULT (o que aconteceu), "
            "STATE (sua compreensão atual). Diga também a parte "
            "STATE em voz alta ao usuário na sua resposta — o Vera nunca lê a "
            "conversa, apenas o que você diz a ele explicitamente, e "
            "também não a interpreta."
        ),
        "protocol": [
            "Antes de qualquer trabalho em uma nova sessão, chame vera_session_start e leia o resultado.",
            "Antes de uma decisão importante, veja as entradas recentes (e o resumo, se houver) para saber o que já foi decidido — não contradiga sem querer algo já registrado. O Vera não vai detectar isso por você; esse julgamento é seu.",
            "Após uma mudança significativa, chame vera_record com REQUEST/CHANGE/REASON/RESULT — não espere a tarefa toda terminar.",
            "Distinga observation, decision, assumption e result — nunca registre um palpite como se fosse um fato.",
            "Nunca sobrescreva um evento passado. A memória do Vera é somente de acréscimo por design; corrija para a frente, não reescreva o histórico.",
            "Quando o usuário disser \"Vera\" no meio da conversa, isso significa: salve o que aconteceu E explique ao usuário sua compreensão atual.",
            "Reconheça \"Vera\"/\"vera\" como gatilho independente de maiúsculas/minúsculas e de onde aparece na mensagem (\"Vera guide\", \"vera guide\", \"abra o Vera guide em alemão\" contam todas), não apenas uma correspondência exata; se a mensagem citar um idioma, use-o nessa chamada, caso contrário use o idioma atual da conversa.",
            "Cite a memória pelo número quando se basear nela (\"segundo #12\") para que o usuário ou uma sessão posterior possa verificar exatamente com vera lookup. Verifique size.over_threshold de vera_stats no início da sessão — se verdadeiro, a memória não compactada cresceu o suficiente para arriscar estourar o contexto de um agente novo; leia-a, escreva um resumo citando os números cobertos, diga ao usuário que compactar pode ajudar, e chame vera_compress.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · vera lookup <n> · "
            "vera search <query> · vera compress --text \"...\" · vera stats"
        ),
        "switch": (
            "Peça o guia em outro idioma e o Vera responde nele — ex.: "
            "\"Start Vera guide in German\". Idiomas suportados: {langs}."
        ),
    },
    "ru": {
        "tagline": "общая, только-добавляемая, цитируемая память для ИИ-агентов разработки.",
        "core_idea": (
            "Сессии заканчиваются. Проект — нет. Claude, локальная модель или "
            "любой другой MCP-совместимый агент может продолжить ровно с того "
            "места, где остановился предыдущий — Claude → Vera → Local → "
            "Vera → Claude — читая одну и ту же память вместо истории вашей "
            "сессии. Vera не интерпретирует то, что хранит — нет извлечения "
            "фактов, нет обнаружения противоречий. Каждая запись просто "
            "получает цитируемый номер (#N); осмыслить её — задача агента, "
            "как человек свободно читает журнал, а не получает готовые выводы."
        ),
        "start": (
            "В начале сессии, ДО начала любой работы, вызовите "
            "vera_session_start (CLI: `vera start`). Он вернёт последний "
            "сжатый дайджест (если он есть) плюс всё, что записано с тех "
            "пор — или, если дайджеста ещё нет, самые последние записи — "
            "каждая со ссылочным номером. Прочитайте это, прежде чем "
            "что-либо трогать."
        ),
        "record": (
            "Когда пользователь говорит \"Vera\", зафиксируйте это через "
            "vera_record (CLI: `vera record`). Сведите разговор к: "
            "REQUEST (что было запрошено), CHANGE (что вы сделали и в каких "
            "файлах), REASON (почему выбрана такая структура), RESULT (что "
            "произошло), STATE (ваше текущее понимание). Часть "
            "STATE также произнесите пользователю в своём ответе — Vera "
            "никогда не читает сам разговор, только то, что вы явно ей "
            "сообщаете, и никак это не интерпретирует."
        ),
        "protocol": [
            "Перед любой работой в новой сессии вызовите vera_session_start и прочитайте результат.",
            "Перед важным решением просмотрите недавние записи (и дайджест, если есть), чтобы узнать, что уже решено — не противоречьте незаметно уже зафиксированному. Vera не отследит это за вас; это ваше собственное суждение.",
            "После значимого изменения вызовите vera_record с REQUEST/CHANGE/REASON/RESULT — не дожидайтесь завершения всей задачи.",
            "Различайте observation, decision, assumption и result — никогда не записывайте догадку как факт.",
            "Никогда не перезаписывайте прошлое событие. Память Vera по конструкции только для добавления; исправляйте вперёд, а не переписывайте историю.",
            "Если пользователь говорит \"Vera\" посреди разговора, это значит: сохраните произошедшее И объясните пользователю своё текущее понимание.",
            "Распознавайте \"Vera\"/\"vera\" как триггер независимо от регистра и места в сообщении (\"Vera guide\", \"vera guide\", \"открой Vera guide на немецком\" — всё подходит), а не только точное совпадение; если в сообщении назван язык, используйте его для этого вызова, иначе — текущий язык разговора по умолчанию.",
            "Ссылайтесь на память по номеру, когда опираетесь на неё (\"согласно #12\"), чтобы пользователь или более поздняя сессия могли точно проверить через vera lookup. Проверяйте size.over_threshold из vera_stats в начале сессии — если true, несжатая память выросла настолько, что рискует переполнить контекст нового агента; прочитайте её, напишите дайджест, цитирующий охваченные номера, скажите пользователю, что сжатие может помочь, и вызовите vera_compress.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · vera lookup <n> · "
            "vera search <query> · vera compress --text \"...\" · vera stats"
        ),
        "switch": (
            "Попросите руководство на другом языке — Vera ответит на нём, "
            "например: \"Start Vera guide in German\". Поддерживаются: {langs}."
        ),
    },
    "it": {
        "tagline": "una memoria condivisa, a sola aggiunta e citabile per agenti di codice IA.",
        "core_idea": (
            "Le sessioni finiscono. Il progetto no. Claude, un modello locale "
            "o qualsiasi altro agente compatibile con MCP può riprendere "
            "esattamente da dove si era fermato l'ultimo — Claude → Vera → "
            "Local → Vera → Claude — leggendo la stessa memoria invece "
            "della cronologia della sessione. Vera non interpreta ciò che "
            "memorizza — niente estrazione di fatti, niente rilevamento di "
            "contraddizioni. Ogni voce riceve solo un numero citabile "
            "(#N); darle un senso è compito dell'agente, come una persona "
            "che legge liberamente un registro invece di ricevere conclusioni."
        ),
        "start": (
            "All'inizio di una sessione, chiama vera_session_start (CLI: "
            "`vera start`) PRIMA di fare qualsiasi cosa. Restituisce "
            "l'ultimo digest compresso (se esiste) più tutto ciò che è "
            "stato registrato da allora — o, se non c'è ancora un digest, "
            "le voci più recenti — ciascuna con un numero di citazione. "
            "Leggilo prima di toccare qualsiasi cosa."
        ),
        "record": (
            "Quando l'utente dice \"Vera\", registra il turno con vera_record "
            "(CLI: `vera record`). Distilla la conversazione in: "
            "REQUEST (cosa è stato chiesto), CHANGE (cosa hai fatto, e in "
            "quali file), REASON (perché quella struttura), RESULT (cosa è "
            "successo), STATE (la tua comprensione attuale). Di' "
            "anche la parte STATE ad alta voce all'utente nella tua risposta "
            "— Vera non legge mai la conversazione, solo ciò che le dici "
            "esplicitamente, e non la interpreta nemmeno."
        ),
        "protocol": [
            "Prima di qualsiasi lavoro in una nuova sessione, chiama vera_session_start e leggi il risultato.",
            "Prima di una decisione importante, scorri le voci recenti (e il digest, se esiste) per vedere cosa è già stato deciso — non contraddire inconsapevolmente qualcosa già registrato. Vera non lo rileverà al posto tuo; quel giudizio è tuo.",
            "Dopo una modifica significativa, chiama vera_record con REQUEST/CHANGE/REASON/RESULT — non aspettare che l'intero compito sia finito.",
            "Distingui observation, decision, assumption e result — non registrare mai una supposizione come se fosse un fatto.",
            "Non sovrascrivere mai un evento passato. La memoria di Vera è a sola aggiunta per progettazione; correggi in avanti, non riscrivere la storia.",
            "Quando l'utente dice \"Vera\" a metà conversazione, significa: salva ciò che è successo E spiega all'utente la tua comprensione attuale.",
            "Riconosci \"Vera\"/\"vera\" come trigger indipendentemente da maiuscole/minuscole e da dove compare nel messaggio (\"Vera guide\", \"vera guide\", \"apri Vera guide in tedesco\" contano tutte), non solo una corrispondenza esatta; se il messaggio nomina una lingua, usala per quella chiamata, altrimenti usa la lingua corrente della conversazione.",
            "Cita la memoria con il suo numero quando ti basi su di essa (\"secondo #12\") così l'utente o una sessione successiva può verificare esattamente con vera lookup. Controlla size.over_threshold di vera_stats all'inizio della sessione — se vero, la memoria non compressa è cresciuta abbastanza da rischiare di far traboccare il contesto di un nuovo agente; leggila, scrivi un digest che cita i numeri coperti, di' all'utente che comprimere potrebbe aiutare, e chiama vera_compress.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · vera lookup <n> · "
            "vera search <query> · vera compress --text \"...\" · vera stats"
        ),
        "switch": (
            "Chiedi la guida in un'altra lingua e Vera risponderà in quella "
            "lingua — es. \"Start Vera guide in German\". Lingue supportate: "
            "{langs}."
        ),
    },
    "ar": {
        "tagline": "ذاكرة مشتركة قابلة للإلحاق فقط وقابلة للاستشهاد لوكلاء البرمجة بالذكاء الاصطناعي.",
        "core_idea": (
            "الجلسات تنتهي. المشروع لا ينتهي. يمكن لـ Claude أو نموذج محلي أو "
            "أي وكيل آخر متوافق مع MCP أن يكمل تمامًا من حيث توقف الوكيل "
            "السابق — Claude ← Vera ← Local ← Vera ← Claude — عبر قراءة "
            "الذاكرة نفسها بدلاً من سجل الجلسة الخاص بك. لا يفسّر Vera ما "
            "يخزّنه — لا استخراج حقائق، ولا كشف تناقضات. كل مُدخل يحصل فقط "
            "على رقم قابل للاستشهاد (#N)؛ فهمه هو مهمة الوكيل، تمامًا كما "
            "يقرأ الشخص سجلًا بحرية بدلاً من تلقي استنتاجات جاهزة."
        ),
        "start": (
            "في بداية الجلسة، استدعِ vera_session_start (سطر الأوامر: `vera "
            "start`) قبل القيام بأي عمل. يُعيد آخر ملخّص مضغوط (إن وُجد) "
            "بالإضافة إلى كل ما سُجّل منذ ذلك الحين — أو، إن لم يوجد ملخّص "
            "بعد، أحدث المُدخلات — كل منها برقم استشهاد. اقرأه قبل أن تلمس "
            "أي شيء."
        ),
        "record": (
            "عندما يقول المستخدم \"Vera\"، سجّل ما جرى باستخدام vera_record "
            "(سطر الأوامر: `vera record`). لخّص المحادثة إلى: REQUEST "
            "(ما طُلب)، CHANGE (ما فعلته، وأي الملفات)، REASON (لماذا اخترت "
            "هذا التصميم)، RESULT (ما الذي حدث)، STATE (فهمك الحالي). واذكر "
            "جزء STATE أيضًا للمستخدم في ردّك — فـVera لا يقرأ المحادثة "
            "أبدًا، بل فقط ما تخبره به صراحةً، ولا يفسّره كذلك."
        ),
        "protocol": [
            "قبل أي عمل في جلسة جديدة، استدعِ vera_session_start واقرأ النتيجة.",
            "قبل اتخاذ قرار مهم، تصفّح المُدخلات الأخيرة (والملخّص إن وُجد) لمعرفة ما تقرر بالفعل — لا تناقض دون علم شيئًا مسجّلًا بالفعل. لن يكتشف Vera هذا نيابة عنك؛ هذا الحكم لك أنت.",
            "بعد أي تغيير مهم، استدعِ vera_record مع REQUEST/CHANGE/REASON/RESULT — لا تنتظر انتهاء المهمة كاملةً.",
            "ميّز بين observation وdecision وassumption وresult — لا تسجّل تخمينًا كأنه حقيقة.",
            "لا تستبدل حدثًا سابقًا أبدًا. ذاكرة Vera قابلة للإلحاق فقط بالتصميم؛ صحّح للأمام، ولا تعِد كتابة التاريخ.",
            "عندما يقول المستخدم \"Vera\" في منتصف المحادثة، يعني ذلك: احفظ ما حدث واشرح للمستخدم فهمك الحالي.",
            "تعرّف على \"Vera\"/\"vera\" كمشغّل بغض النظر عن حالة الأحرف أو موضعها في الرسالة (\"Vera guide\"، \"vera guide\"، \"افتح Vera guide بالألمانية\" كلها تُحتسب)، وليس فقط عند التطابق التام؛ إذا ذكرت الرسالة لغة، استخدمها لهذا الاستدعاء، وإلا استخدم لغة المحادثة الحالية افتراضيًا.",
            "استشهد بالذاكرة برقمها عند الاعتماد عليها (\"وفق #12\") ليتمكن المستخدم أو جلسة لاحقة من التحقق بدقة عبر vera lookup. تحقق من size.over_threshold في vera_stats عند بداية الجلسة — إذا كانت صحيحة، فإن الذاكرة غير المضغوطة نمت بما يكفي لتهديد سياق وكيل جديد بالفيض؛ اقرأها، اكتب ملخصًا يستشهد بالأرقام التي يغطيها، أخبر المستخدم أن الضغط قد يساعد، واستدعِ vera_compress.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · vera lookup <n> · "
            "vera search <query> · vera compress --text \"...\" · vera stats"
        ),
        "switch": (
            "اطلب الدليل بلغة أخرى وسيجيب Vera بها — مثل \"Start Vera guide in "
            "German\". اللغات المدعومة: {langs}."
        ),
    },
    "hi": {
        "tagline": "AI कोडिंग एजेंटों के लिए एक साझा, केवल-जोड़ने-योग्य, उद्धरण-योग्य मेमोरी।",
        "core_idea": (
            "सत्र समाप्त होते हैं। प्रोजेक्ट नहीं। Claude, कोई स्थानीय मॉडल, या कोई भी "
            "अन्य MCP-संगत एजेंट ठीक वहीं से जारी रख सकता है जहाँ पिछला रुका था — "
            "Claude → Vera → Local → Vera → Claude — आपके सत्र इतिहास के बजाय उसी "
            "मेमोरी को पढ़कर। Vera जो संग्रहीत करता है उसकी व्याख्या नहीं करता — न तथ्य "
            "निष्कर्षण, न विरोधाभास पहचान। हर प्रविष्टि को बस एक उद्धरण-योग्य नंबर (#N) "
            "मिलता है; उसका अर्थ निकालना एजेंट का काम है, जैसे कोई व्यक्ति निष्कर्ष सौंपे "
            "जाने के बजाय लॉग को स्वतंत्र रूप से पढ़ता है।"
        ),
        "start": (
            "सत्र शुरू होते ही, कोई भी काम करने से पहले vera_session_start "
            "(CLI: `vera start`) कॉल करें। यह नवीनतम संकुचित डाइजेस्ट (यदि कोई है) "
            "और उसके बाद दर्ज हर चीज़ लौटाता है — या, यदि अभी तक कोई डाइजेस्ट नहीं है, "
            "तो हाल की प्रविष्टियाँ — हर एक उद्धरण नंबर के साथ। कुछ भी छूने से पहले इसे पढ़ें।"
        ),
        "record": (
            "जब उपयोगकर्ता \"Vera\" कहे, तो vera_record (CLI: `vera "
            "record`) से उस बातचीत को दर्ज करें। बातचीत को इनमें बाँटें: REQUEST "
            "(क्या माँगा गया), CHANGE (आपने क्या किया, किन फ़ाइलों में), REASON "
            "(यह संरचना क्यों चुनी), RESULT (क्या हुआ), STATE (आपकी वर्तमान "
            "समझ)। STATE वाला हिस्सा अपने जवाब में उपयोगकर्ता को भी बताएँ — Vera "
            "बातचीत को कभी नहीं पढ़ता, केवल वही जो आप उसे स्पष्ट रूप से बताते हैं, और "
            "उसकी व्याख्या भी नहीं करता।"
        ),
        "protocol": [
            "नए सत्र में कोई भी काम शुरू करने से पहले vera_session_start कॉल करें और परिणाम पढ़ें।",
            "किसी महत्वपूर्ण निर्णय से पहले, हाल की प्रविष्टियों (और यदि हो तो डाइजेस्ट) को देखें कि पहले से क्या तय हो चुका है — बिना जाने पहले से दर्ज किसी बात का खंडन न करें। यह Vera आपके लिए नहीं पकड़ेगा; यह निर्णय आपका अपना है।",
            "किसी बड़े बदलाव के बाद, पूरा काम खत्म होने का इंतज़ार किए बिना vera_record से REQUEST/CHANGE/REASON/RESULT दर्ज करें।",
            "observation, decision, assumption और result में फ़र्क़ करें — किसी अनुमान को तथ्य की तरह दर्ज न करें।",
            "किसी पुराने इवेंट को कभी न बदलें। Vera की मेमोरी डिज़ाइन से केवल-जोड़ने-योग्य है; सुधार आगे बढ़कर दर्ज करें, इतिहास को फिर से न लिखें।",
            "बातचीत के बीच में जब उपयोगकर्ता \"Vera\" कहे, इसका मतलब है: जो हुआ उसे सहेजें, और अपनी वर्तमान समझ उपयोगकर्ता को समझाएँ।",
            "\"Vera\"/\"vera\" को केस या संदेश में स्थिति की परवाह किए बिना ट्रिगर के रूप में पहचानें (\"Vera guide\", \"vera guide\", \"जर्मन में Vera guide खोलो\" सभी मान्य हैं), केवल सटीक मिलान नहीं; यदि संदेश में कोई भाषा बताई गई है तो उसी में जवाब दें, अन्यथा बातचीत की मौजूदा भाषा डिफ़ॉल्ट रहे।",
            "जब मेमोरी पर भरोसा करें तो उसे नंबर से उद्धृत करें (\"#12 के अनुसार\") ताकि उपयोगकर्ता या बाद का सत्र vera lookup से ठीक-ठीक जाँच सके। सत्र शुरू होने पर vera_stats का size.over_threshold जाँचें — यदि true है, तो असंकुचित मेमोरी इतनी बड़ी हो गई है कि किसी नए एजेंट के संदर्भ को भरने का जोखिम है; इसे पढ़ें, कवर किए गए नंबरों को उद्धृत करने वाला डाइजेस्ट लिखें, उपयोगकर्ता को बताएँ कि संकुचन मदद कर सकता है, और vera_compress कॉल करें।",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · vera lookup <n> · "
            "vera search <query> · vera compress --text \"...\" · vera stats"
        ),
        "switch": (
            "किसी अन्य भाषा में गाइड माँगें और Vera उसी में जवाब देगा — जैसे "
            "\"Start Vera guide in German\"। समर्थित भाषाएँ: {langs}।"
        ),
    },
}


_LABELS: Dict[str, Dict[str, str]] = {
    "en": {
        "header": "MEMORY",
        "digest": "Compressed digest",
        "recent": "Recent entries",
        "none": "(none yet)",
        "protocol_header": "AGENT PROTOCOL (read this every session)",
        "size_ok": "under compression threshold",
        "size_over": "OVER compression threshold — consider vera_compress",
    },
    "ja": {
        "header": "MEMORY",
        "digest": "圧縮ダイジェスト",
        "recent": "直近のエントリ",
        "none": "（まだありません）",
        "protocol_header": "AGENT PROTOCOL（毎セッション必読）",
        "size_ok": "圧縮閾値未満",
        "size_over": "圧縮閾値を超過 — vera_compressを検討してください",
    },
    "zh": {
        "header": "MEMORY",
        "digest": "压缩摘要",
        "recent": "最近的条目",
        "none": "（暂无）",
        "protocol_header": "AGENT PROTOCOL（每次会话必读）",
        "size_ok": "低于压缩阈值",
        "size_over": "已超过压缩阈值 — 请考虑 vera_compress",
    },
    "es": {
        "header": "MEMORY",
        "digest": "Resumen comprimido",
        "recent": "Entradas recientes",
        "none": "(aún ninguno)",
        "protocol_header": "AGENT PROTOCOL (leer cada sesión)",
        "size_ok": "por debajo del umbral de compresión",
        "size_over": "SUPERA el umbral de compresión — considera vera_compress",
    },
    "fr": {
        "header": "MEMORY",
        "digest": "Résumé compressé",
        "recent": "Entrées récentes",
        "none": "(aucun pour l'instant)",
        "protocol_header": "AGENT PROTOCOL (à lire à chaque session)",
        "size_ok": "sous le seuil de compression",
        "size_over": "AU-DESSUS du seuil de compression — envisagez vera_compress",
    },
    "de": {
        "header": "MEMORY",
        "digest": "Komprimierte Zusammenfassung",
        "recent": "Aktuelle Einträge",
        "none": "(noch keine)",
        "protocol_header": "AGENT PROTOCOL (jede Sitzung lesen)",
        "size_ok": "unter dem Komprimierungsschwellenwert",
        "size_over": "ÜBER dem Komprimierungsschwellenwert — vera_compress erwägen",
    },
    "ko": {
        "header": "MEMORY",
        "digest": "압축 다이제스트",
        "recent": "최근 항목",
        "none": "(아직 없음)",
        "protocol_header": "AGENT PROTOCOL (매 세션 필독)",
        "size_ok": "압축 임계값 이하",
        "size_over": "압축 임계값 초과 — vera_compress 고려",
    },
    "pt": {
        "header": "MEMORY",
        "digest": "Resumo compactado",
        "recent": "Entradas recentes",
        "none": "(nenhum ainda)",
        "protocol_header": "AGENT PROTOCOL (ler a cada sessão)",
        "size_ok": "abaixo do limite de compactação",
        "size_over": "ACIMA do limite de compactação — considere vera_compress",
    },
    "ru": {
        "header": "MEMORY",
        "digest": "Сжатый дайджест",
        "recent": "Недавние записи",
        "none": "(пока нет)",
        "protocol_header": "AGENT PROTOCOL (читать каждую сессию)",
        "size_ok": "ниже порога сжатия",
        "size_over": "ВЫШЕ порога сжатия — рассмотрите vera_compress",
    },
    "it": {
        "header": "MEMORY",
        "digest": "Digest compresso",
        "recent": "Voci recenti",
        "none": "(nessuno ancora)",
        "protocol_header": "AGENT PROTOCOL (da leggere ogni sessione)",
        "size_ok": "sotto la soglia di compressione",
        "size_over": "SOPRA la soglia di compressione — valuta vera_compress",
    },
    "ar": {
        "header": "MEMORY",
        "digest": "ملخّص مضغوط",
        "recent": "المُدخلات الأخيرة",
        "none": "(لا يوجد بعد)",
        "protocol_header": "AGENT PROTOCOL (اقرأ في كل جلسة)",
        "size_ok": "دون عتبة الضغط",
        "size_over": "فوق عتبة الضغط — فكّر في vera_compress",
    },
    "hi": {
        "header": "MEMORY",
        "digest": "संकुचित डाइजेस्ट",
        "recent": "हाल की प्रविष्टियाँ",
        "none": "(अभी तक कोई नहीं)",
        "protocol_header": "AGENT PROTOCOL (हर सत्र में पढ़ें)",
        "size_ok": "संकुचन सीमा से नीचे",
        "size_over": "संकुचन सीमा से ऊपर — vera_compress पर विचार करें",
    },
}


def render_protocol(lang: str = DEFAULT_LANG) -> str:
    """Just the agent behavior protocol — re-stated every session without
    re-explaining what Vera is."""
    lang = resolve_lang(lang)
    g = _GUIDE[lang]
    lab = _LABELS[lang]
    bullets = "\n".join(f"- {rule}" for rule in g["protocol"])
    return f"{lab['protocol_header']}\n{bullets}"


def render_guide(lang: str = DEFAULT_LANG) -> str:
    """Full onboarding explanation of Vera in the requested language."""
    lang = resolve_lang(lang)
    g = _GUIDE[lang]
    switch = g["switch"].format(langs=_langs_str(lang))
    sections = [
        f"# Vera — {g['tagline']}",
        g["core_idea"],
        g["start"],
        g["record"],
        render_protocol(lang),
        f"COMMANDS\n{g['commands']}",
        switch,
    ]
    return "\n\n".join(sections)


def render_project_state(state: Dict[str, Any], lang: str = DEFAULT_LANG) -> str:
    """Format VeraStore.get_project_state() as the MEMORY block a new
    session should read first, ending with the protocol reminder."""
    lang = resolve_lang(lang)
    lab = _LABELS[lang]

    parts = [lab["header"], ""]

    digest = state.get("digest")
    parts.append(f"{lab['digest']}:")
    if digest:
        parts.append(f"  (through #{digest['through_n']}, {digest['author']}, {digest['ts']})")
        for line in digest["text"].splitlines():
            parts.append(f"  {line}")
    else:
        parts.append(f"  {lab['none']}")
    parts.append("")

    recent = state.get("recent_entries", [])
    parts.append(f"{lab['recent']}:")
    if recent:
        for e in recent:
            files = f" ({', '.join(e['files'])})" if e.get("files") else ""
            parts.append(f"  #{e['n']} [{e['type']}/{e['author']}] {e['content']}{files}")
    else:
        parts.append(f"  {lab['none']}")
    parts.append("")

    size = state.get("size", {})
    size_line = lab["size_over"] if size.get("over_threshold") else lab["size_ok"]
    parts.append(
        f"size: {size.get('uncompressed_entries', 0)} entries, "
        f"~{size.get('estimated_tokens', 0)} tokens since #{size.get('since_n', 0)} — {size_line}"
    )
    parts.append("")

    parts.append(render_protocol(lang))
    return "\n".join(parts)
