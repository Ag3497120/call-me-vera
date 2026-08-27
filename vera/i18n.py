"""Vera guide & agent-protocol text, in every supported language.

Structural field names (REQUEST / CHANGE / REASON / RESULT / STATE, and the
PROJECT CONTEXT labels) stay as short fixed English tokens in every
language — they're machine-consistent anchors an agent can rely on
regardless of which language the surrounding prose is in. Only the
explanatory prose and protocol rules are localized.

`render_guide(lang)`   — full onboarding explanation: what Vera is, how to
                          start a session, how to record with it, the agent
                          behavior protocol, available commands.
`render_protocol(lang)`— just the agent behavior protocol (used inside
                          vera_session_start's response, so it's re-stated
                          every session without re-explaining all of Vera).
`render_project_state(state, lang)` — formats VeraStore.get_project_state()
                          as the PROJECT CONTEXT block a new session reads
                          first.
`resolve_lang(text)`   — normalize a code or language name ("de", "German",
                          "Deutsch", "ドイツ語") to a supported code.
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
        "tagline": "a shared, append-only project memory for AI coding agents.",
        "core_idea": (
            "Sessions end. The project doesn't. Claude, a local model, or any "
            "other MCP-compatible agent can pick up exactly where the last one "
            "left off — Claude → Vera → Local → Vera → Claude — by reading the "
            "same event log instead of your session history."
        ),
        "start": (
            "At the start of a session, call vera_session_start (CLI: "
            "`vera start`) BEFORE doing any work. It returns the "
            "project's current state: the latest interpretation of the "
            "codebase, active constraints, open contradictions, and recent "
            "decisions/changes/unresolved items. Read it before you touch "
            "anything."
        ),
        "record": (
            "When the user says \"Vera\", record the turn with vera_record "
            "(CLI: `vera record`). Distill the conversation into: "
            "REQUEST (what was asked), CHANGE (what you did, and which files), "
            "REASON (why you structured it that way), RESULT (what happened), "
            "STATE (your current understanding of the codebase). Also say the "
            "STATE part out loud to the user in your reply — Vera never reads "
            "your conversation, only what you explicitly tell it."
        ),
        "protocol": [
            "Before doing any work in a new session, call vera_session_start and read the result.",
            "Before changing architecture, check active_constraints and recent_decisions — don't silently contradict a past decision.",
            "After a significant change, call vera_record with REQUEST/CHANGE/REASON/RESULT — don't wait until the whole task is done.",
            "Distinguish observation, decision, assumption, and result — never record a guess as if it were a fact.",
            "Never overwrite a past event. Vera's event log is append-only by design; correct forward, don't rewrite history.",
            "When the user says \"Vera\" mid-conversation, that means: save what happened, AND explain your current understanding of the codebase to the user.",
            "Recognize \"Vera\"/\"vera\" as the trigger in any case and anywhere in the message — \"Vera guide\", \"vera guide\", \"open Vera guide in German\", 「現在のVera guideを見せて」 all count, not just an exact match; if the message names a language, use it for that call, otherwise default to the conversation's current language.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · "
            "vera search <query> · vera check --action <a> · vera pause / vera resume · vera status"
        ),
        "switch": (
            "Ask for the guide in another language and Vera answers in it — "
            "e.g. \"Start Vera guide in German\", or in Japanese: "
            "「Vera guideをドイツ語で起動して」. Supported: {langs}."
        ),
    },
    "ja": {
        "tagline": "AIコーディングエージェントのための、共有・追記専用のプロジェクト記憶。",
        "core_idea": (
            "セッションは終わっても、プロジェクトは終わりません。Claude、ローカルモデル、"
            "他のMCP対応エージェントは、あなたのセッション履歴ではなく同じイベントログを"
            "読むことで、直前の作業をそのまま引き継げます — Claude → Vera → Local → Vera → Claude。"
        ),
        "start": (
            "セッション開始時、作業を始める前に vera_session_start（CLI: `vera start`）"
            "を必ず呼んでください。プロジェクトの現在状態 — コードベースの最新の解釈、"
            "有効な制約、未解決の矛盾、直近の決定・変更・未解決事項 — が返されます。"
            "何かに触れる前に必ず読んでください。"
        ),
        "record": (
            "ユーザーが「Vera」と言ったら、vera_record（CLI: `vera record`）で"
            "そのやり取りを記録してください。会話を REQUEST（何を求められたか）、"
            "CHANGE（何をしたか、どのファイルか）、REASON（なぜその構造にしたか）、"
            "RESULT（何が起きたか）、STATE（コードベースを現在どう解釈しているか）に"
            "整理してください。STATEの内容は返信の中でユーザーにも説明してください — "
            "Veraは会話そのものを見ておらず、あなたが明示的に伝えたことだけを記録します。"
        ),
        "protocol": [
            "新しいセッションで作業を始める前に、必ず vera_session_start を呼び、結果を読むこと。",
            "アーキテクチャを変更する前に active_constraints と recent_decisions を確認すること。過去の決定に気づかず反する変更をしないこと。",
            "大きな変更のあとは、タスク全体が終わるのを待たず、その都度 vera_record で REQUEST/CHANGE/REASON/RESULT を記録すること。",
            "観察（observation）・決定（decision）・仮定（assumption）・結果（result）を区別すること。推測を事実として記録しないこと。",
            "過去のイベントを絶対に上書きしないこと。Veraのイベントログは設計上追記専用。訂正は前進させて記録する（履歴の書き換えはしない）。",
            "会話の途中でユーザーが「Vera」と言ったら、それは『今の作業内容を保存し、コードベースの現在の解釈をユーザーに説明する』という意味。",
            "「Vera」「vera」は大文字小文字を問わず、メッセージ中のどこにあってもトリガーとして認識すること（「Vera guide」「vera guide」「現在のVera guideを見せて」「ドイツ語でVera guideを起動して」すべて該当）。メッセージ内で言語が指定されていればその言語で、指定がなければ会話中の現在の言語をデフォルトにすること。",
        ],
        "commands": (
            "vera start ・ vera record ・ vera guide [--lang xx] ・ "
            "vera search <query> ・ vera check --action <a> ・ vera pause / vera resume ・ vera status"
        ),
        "switch": (
            "他の言語でガイドを見たいときは、そう伝えるだけで構いません（例:"
            "「ドイツ語でVera guideを起動して」、英語なら \"Start Vera guide in German\"）。"
            "対応言語: {langs}。"
        ),
    },
    "zh": {
        "tagline": "面向AI编程智能体的共享、仅追加式项目记忆。",
        "core_idea": (
            "会话会结束，项目不会。Claude、本地模型或任何兼容MCP的智能体，都可以通过读取"
            "同一份事件日志（而不是你的会话历史）来准确衔接上一次的工作 —— "
            "Claude → Vera → Local → Vera → Claude。"
        ),
        "start": (
            "会话开始时，在开始任何工作之前先调用 vera_session_start"
            "（CLI：`vera start`）。它会返回项目当前状态：对代码库的最新理解、"
            "生效中的约束、尚未解决的矛盾，以及最近的决策/变更/未解决事项。"
            "动手之前请先读完。"
        ),
        "record": (
            "当用户说“Vera”时，用 vera_record（CLI：`vera record`）记录这次交互。"
            "把对话提炼为：REQUEST（被要求做什么）、CHANGE（做了什么、涉及哪些文件）、"
            "REASON（为什么这样设计）、RESULT（发生了什么）、STATE（你目前对代码库的理解）。"
            "STATE部分也要在回复里对用户说出来 —— Vera不会旁听对话，只记录你明确告诉它的内容。"
        ),
        "protocol": [
            "在新会话中开始任何工作之前，先调用 vera_session_start 并阅读结果。",
            "在改动架构之前，检查 active_constraints 和 recent_decisions —— 不要在不知情的情况下违背过去的决定。",
            "发生重要变更后，立即用 vera_record 记录 REQUEST/CHANGE/REASON/RESULT，不要等到整个任务结束。",
            "区分 observation（观察）、decision（决定）、assumption（假设）、result（结果）—— 不要把猜测当作事实记录。",
            "绝不覆盖过去的事件。Vera的事件日志按设计仅可追加；有修正就继续追加新记录，不要改写历史。",
            "对话中用户说“Vera”，意味着：保存刚才发生的事，并向用户说明你目前对代码库的理解。",
            "无论大小写，无论出现在消息的哪个位置，都要把“Vera”/“vera”识别为触发词（“Vera guide”“vera guide”“用德语打开Vera guide”“显示当前的Vera guide”均算数），不要求完全匹配；消息中指明了语言就用该语言调用，否则默认使用当前对话所用的语言。",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · "
            "vera search <query> · vera check --action <a> · vera pause / vera resume · vera status"
        ),
        "switch": (
            "想用其他语言看指南，直接说出来就行（例如 “Start Vera guide in German”）。"
            "支持的语言：{langs}。"
        ),
    },
    "es": {
        "tagline": "una memoria de proyecto compartida y de solo anexado para agentes de codificación con IA.",
        "core_idea": (
            "Las sesiones terminan. El proyecto no. Claude, un modelo local o "
            "cualquier otro agente compatible con MCP puede continuar justo donde "
            "quedó el anterior — Claude → Vera → Local → Vera → Claude — leyendo "
            "el mismo registro de eventos en lugar de tu historial de sesión."
        ),
        "start": (
            "Al iniciar una sesión, llama a vera_session_start (CLI: `vera "
            "start`) ANTES de hacer nada. Devuelve el estado actual del "
            "proyecto: la última interpretación del código, restricciones "
            "activas, contradicciones abiertas y decisiones/cambios/pendientes "
            "recientes. Léelo antes de tocar nada."
        ),
        "record": (
            "Cuando el usuario diga \"Vera\", registra el turno con vera_record "
            "(CLI: `vera record`). Destila la conversación en: REQUEST "
            "(qué se pidió), CHANGE (qué hiciste y en qué archivos), REASON "
            "(por qué lo estructuraste así), RESULT (qué ocurrió), STATE (tu "
            "comprensión actual del código). Explica también el STATE al "
            "usuario en tu respuesta — Vera nunca lee la conversación, solo lo "
            "que le indicas explícitamente."
        ),
        "protocol": [
            "Antes de trabajar en una sesión nueva, llama a vera_session_start y lee el resultado.",
            "Antes de cambiar la arquitectura, revisa active_constraints y recent_decisions — no contradigas sin querer una decisión pasada.",
            "Tras un cambio importante, llama a vera_record con REQUEST/CHANGE/REASON/RESULT — no esperes a terminar toda la tarea.",
            "Distingue observation, decision, assumption y result — nunca registres una suposición como si fuera un hecho.",
            "Nunca sobrescribas un evento pasado. El registro de Vera es de solo anexado por diseño; corrige hacia adelante, no reescribas la historia.",
            "Cuando el usuario diga \"Vera\" a mitad de la conversación, significa: guarda lo ocurrido y explica al usuario tu comprensión actual del código.",
            "Reconoce \"Vera\"/\"vera\" como disparador en cualquier mayúscula/minúscula y en cualquier parte del mensaje (\"Vera guide\", \"vera guide\", \"abre Vera guide en alemán\" cuentan todas), no solo una coincidencia exacta; si el mensaje nombra un idioma, úsalo para esa llamada, si no, usa por defecto el idioma actual de la conversación.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · "
            "vera search <query> · vera check --action <a> · vera pause / vera resume · vera status"
        ),
        "switch": (
            "Pide la guía en otro idioma y Vera responderá en él — p. ej. "
            "\"Start Vera guide in German\". Idiomas admitidos: {langs}."
        ),
    },
    "fr": {
        "tagline": "une mémoire de projet partagée et en ajout seul pour les agents de code IA.",
        "core_idea": (
            "Les sessions se terminent. Pas le projet. Claude, un modèle local "
            "ou tout autre agent compatible MCP peut reprendre exactement là où "
            "le précédent s'est arrêté — Claude → Vera → Local → Vera → Claude "
            "— en lisant le même journal d'événements plutôt que votre "
            "historique de session."
        ),
        "start": (
            "Au début d'une session, appelez vera_session_start (CLI : `vera "
            "start`) AVANT toute action. Cela renvoie l'état actuel du "
            "projet : dernière interprétation du code, contraintes actives, "
            "contradictions ouvertes, décisions/changements/points en suspens "
            "récents. Lisez-le avant de toucher à quoi que ce soit."
        ),
        "record": (
            "Quand l'utilisateur dit \"Vera\", enregistrez l'échange avec "
            "vera_record (CLI : `vera record`). Distillez la "
            "conversation en : REQUEST (ce qui a été demandé), CHANGE (ce que "
            "vous avez fait, et quels fichiers), REASON (pourquoi cette "
            "structure), RESULT (ce qui s'est passé), STATE (votre "
            "compréhension actuelle du code). Dites aussi le STATE à voix "
            "haute à l'utilisateur dans votre réponse — Vera ne lit jamais la "
            "conversation, seulement ce que vous lui dites explicitement."
        ),
        "protocol": [
            "Avant tout travail dans une nouvelle session, appelez vera_session_start et lisez le résultat.",
            "Avant de modifier l'architecture, vérifiez active_constraints et recent_decisions — ne contredisez pas une décision passée sans le savoir.",
            "Après un changement important, appelez vera_record avec REQUEST/CHANGE/REASON/RESULT — n'attendez pas la fin de toute la tâche.",
            "Distinguez observation, decision, assumption et result — n'enregistrez jamais une supposition comme un fait.",
            "N'écrasez jamais un événement passé. Le journal de Vera est en ajout seul par conception ; corrigez en avançant, ne réécrivez pas l'historique.",
            "Quand l'utilisateur dit \"Vera\" en cours de conversation, cela signifie : enregistrez ce qui s'est passé ET expliquez à l'utilisateur votre compréhension actuelle du code.",
            "Reconnaissez \"Vera\"/\"vera\" comme déclencheur quelle que soit la casse et où qu'il apparaisse dans le message (\"Vera guide\", \"vera guide\", \"ouvre Vera guide en allemand\" comptent toutes), pas seulement une correspondance exacte ; si le message nomme une langue, utilisez-la pour cet appel, sinon utilisez par défaut la langue actuelle de la conversation.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · "
            "vera search <query> · vera check --action <a> · vera pause / vera resume · vera status"
        ),
        "switch": (
            "Demandez le guide dans une autre langue et Vera répondra dans "
            "cette langue — p. ex. \"Start Vera guide in German\". Langues "
            "prises en charge : {langs}."
        ),
    },
    "de": {
        "tagline": "ein geteiltes, nur-anhängendes Projektgedächtnis für KI-Coding-Agenten.",
        "core_idea": (
            "Sitzungen enden. Das Projekt nicht. Claude, ein lokales Modell "
            "oder jeder andere MCP-kompatible Agent kann genau dort "
            "weitermachen, wo der letzte aufgehört hat — Claude → Vera → "
            "Local → Vera → Claude — indem dasselbe Ereignisprotokoll statt "
            "des Sitzungsverlaufs gelesen wird."
        ),
        "start": (
            "Rufen Sie zu Beginn einer Sitzung vera_session_start auf (CLI: "
            "`vera start`), BEVOR Sie irgendetwas tun. Es liefert den "
            "aktuellen Projektstatus: die neueste Interpretation der Codebasis, "
            "aktive Constraints, offene Widersprüche sowie aktuelle "
            "Entscheidungen/Änderungen/offene Punkte. Lesen Sie es, bevor Sie "
            "irgendetwas anfassen."
        ),
        "record": (
            "Wenn der Nutzer \"Vera\" sagt, protokollieren Sie den Vorgang mit "
            "vera_record (CLI: `vera record`). Destillieren Sie das "
            "Gespräch zu: REQUEST (was verlangt wurde), CHANGE (was Sie getan "
            "haben, welche Dateien), REASON (warum diese Struktur), RESULT "
            "(was passiert ist), STATE (Ihr aktuelles Verständnis der "
            "Codebasis). Sprechen Sie den STATE-Teil auch in Ihrer Antwort an "
            "den Nutzer aus — Vera liest niemals das Gespräch selbst, nur was "
            "Sie ihm ausdrücklich mitteilen."
        ),
        "protocol": [
            "Rufen Sie vor jeder Arbeit in einer neuen Sitzung vera_session_start auf und lesen Sie das Ergebnis.",
            "Prüfen Sie vor Architekturänderungen active_constraints und recent_decisions — widersprechen Sie nicht unbemerkt einer früheren Entscheidung.",
            "Rufen Sie nach einer wesentlichen Änderung vera_record mit REQUEST/CHANGE/REASON/RESULT auf — warten Sie nicht, bis die ganze Aufgabe fertig ist.",
            "Unterscheiden Sie observation, decision, assumption und result — protokollieren Sie niemals eine Vermutung als Tatsache.",
            "Überschreiben Sie niemals ein vergangenes Ereignis. Veras Ereignisprotokoll ist per Design nur-anhängend; korrigieren Sie vorwärts, statt Geschichte umzuschreiben.",
            "Wenn der Nutzer mitten im Gespräch \"Vera\" sagt, bedeutet das: Speichern Sie, was passiert ist, UND erklären Sie dem Nutzer Ihr aktuelles Verständnis der Codebasis.",
            "Erkennen Sie \"Vera\"/\"vera\" unabhängig von Groß-/Kleinschreibung und Position in der Nachricht als Auslöser (\"Vera guide\", \"vera guide\", \"Vera guide auf Deutsch öffnen\" zählen alle), nicht nur bei exakter Übereinstimmung; nennt die Nachricht eine Sprache, verwenden Sie diese für den Aufruf, andernfalls die aktuelle Sprache des Gesprächs.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · "
            "vera search <query> · vera check --action <a> · vera pause / vera resume · vera status"
        ),
        "switch": (
            "Fragen Sie nach dem Guide in einer anderen Sprache, und Vera "
            "antwortet darin — z. B. \"Vera guide auf Deutsch starten\". "
            "Unterstützt: {langs}."
        ),
    },
    "ko": {
        "tagline": "AI 코딩 에이전트를 위한 공유형, 추가 전용 프로젝트 기억.",
        "core_idea": (
            "세션은 끝나지만 프로젝트는 끝나지 않습니다. Claude, 로컬 모델, 또는 다른 "
            "MCP 호환 에이전트는 세션 기록이 아니라 동일한 이벤트 로그를 읽음으로써 "
            "이전 작업을 정확히 이어받을 수 있습니다 — Claude → Vera → Local → Vera → Claude."
        ),
        "start": (
            "세션을 시작할 때는 작업을 하기 전에 반드시 vera_session_start"
            "(CLI: `vera start`)를 호출하세요. 프로젝트의 현재 상태 — "
            "코드베이스에 대한 최신 해석, 활성 제약 조건, 미해결 모순, 최근 결정/변경/"
            "미해결 항목 — 이 반환됩니다. 무엇이든 손대기 전에 반드시 읽으세요."
        ),
        "record": (
            "사용자가 \"Vera\"라고 말하면 vera_record(CLI: `vera record`)로 "
            "그 내용을 기록하세요. 대화를 REQUEST(무엇을 요청받았는지), CHANGE(무엇을 "
            "했는지, 어떤 파일인지), REASON(왜 그렇게 구성했는지), RESULT(무슨 일이 "
            "일어났는지), STATE(코드베이스에 대한 현재 이해)로 정리하세요. STATE 내용은 "
            "답변에서 사용자에게도 설명하세요 — Vera는 대화를 직접 보지 않고, 당신이 "
            "명시적으로 알려준 것만 기록합니다."
        ),
        "protocol": [
            "새 세션에서 작업을 시작하기 전에 반드시 vera_session_start를 호출하고 결과를 읽을 것.",
            "아키텍처를 변경하기 전에 active_constraints와 recent_decisions를 확인할 것 — 과거 결정을 모르고 위반하지 말 것.",
            "중요한 변경 후에는 전체 작업이 끝날 때까지 기다리지 말고 그때그때 vera_record로 REQUEST/CHANGE/REASON/RESULT를 기록할 것.",
            "observation(관찰)·decision(결정)·assumption(가정)·result(결과)를 구분할 것 — 추측을 사실처럼 기록하지 말 것.",
            "과거 이벤트를 절대 덮어쓰지 말 것. Vera의 이벤트 로그는 설계상 추가 전용이며, 정정은 앞으로 나아가며 기록하는 것이지 역사를 다시 쓰는 것이 아님.",
            "대화 중 사용자가 \"Vera\"라고 말하면, 그것은 '지금까지의 작업을 저장하고 코드베이스에 대한 현재 이해를 사용자에게 설명하라'는 뜻.",
            "\"Vera\"/\"vera\"는 대소문자나 메시지 내 위치와 무관하게 트리거로 인식할 것(\"Vera guide\", \"vera guide\", \"독일어로 Vera guide 열어줘\" 모두 해당) — 정확히 일치할 때만이 아님. 메시지에 언어가 명시되어 있으면 그 언어를 사용하고, 없으면 현재 대화 언어를 기본값으로 할 것.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · "
            "vera search <query> · vera check --action <a> · vera pause / vera resume · vera status"
        ),
        "switch": (
            "다른 언어로 가이드를 보고 싶다면 그렇게 요청하면 됩니다 (예: "
            "\"Start Vera guide in German\"). 지원 언어: {langs}."
        ),
    },
    "pt": {
        "tagline": "uma memória de projeto compartilhada e somente de acréscimo para agentes de código com IA.",
        "core_idea": (
            "As sessões terminam. O projeto não. Claude, um modelo local ou "
            "qualquer outro agente compatível com MCP pode continuar exatamente "
            "de onde o anterior parou — Claude → Vera → Local → Vera → Claude "
            "— lendo o mesmo registro de eventos em vez do seu histórico de "
            "sessão."
        ),
        "start": (
            "No início de uma sessão, chame vera_session_start (CLI: `vera "
            "start`) ANTES de fazer qualquer coisa. Isso retorna o "
            "estado atual do projeto: a interpretação mais recente do código, "
            "restrições ativas, contradições em aberto e decisões/"
            "mudanças/pendências recentes. Leia antes de tocar em qualquer "
            "coisa."
        ),
        "record": (
            "Quando o usuário disser \"Vera\", registre o turno com vera_record "
            "(CLI: `vera record`). Resuma a conversa em: REQUEST (o "
            "que foi pedido), CHANGE (o que você fez, e quais arquivos), "
            "REASON (por que estruturou assim), RESULT (o que aconteceu), "
            "STATE (sua compreensão atual do código). Diga também a parte "
            "STATE em voz alta ao usuário na sua resposta — o Vera nunca lê a "
            "conversa, apenas o que você diz a ele explicitamente."
        ),
        "protocol": [
            "Antes de qualquer trabalho em uma nova sessão, chame vera_session_start e leia o resultado.",
            "Antes de mudar a arquitetura, verifique active_constraints e recent_decisions — não contradiga sem querer uma decisão passada.",
            "Após uma mudança significativa, chame vera_record com REQUEST/CHANGE/REASON/RESULT — não espere a tarefa toda terminar.",
            "Distinga observation, decision, assumption e result — nunca registre um palpite como se fosse um fato.",
            "Nunca sobrescreva um evento passado. O registro do Vera é somente de acréscimo por design; corrija para a frente, não reescreva o histórico.",
            "Quando o usuário disser \"Vera\" no meio da conversa, isso significa: salve o que aconteceu E explique ao usuário sua compreensão atual do código.",
            "Reconheça \"Vera\"/\"vera\" como gatilho independente de maiúsculas/minúsculas e de onde aparece na mensagem (\"Vera guide\", \"vera guide\", \"abra o Vera guide em alemão\" contam todas), não apenas uma correspondência exata; se a mensagem citar um idioma, use-o nessa chamada, caso contrário use o idioma atual da conversa.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · "
            "vera search <query> · vera check --action <a> · vera pause / vera resume · vera status"
        ),
        "switch": (
            "Peça o guia em outro idioma e o Vera responde nele — ex.: "
            "\"Start Vera guide in German\". Idiomas suportados: {langs}."
        ),
    },
    "ru": {
        "tagline": "общая, только-добавляемая память проекта для ИИ-агентов разработки.",
        "core_idea": (
            "Сессии заканчиваются. Проект — нет. Claude, локальная модель или "
            "любой другой MCP-совместимый агент может продолжить ровно с того "
            "места, где остановился предыдущий — Claude → Vera → Local → "
            "Vera → Claude — читая один и тот же журнал событий вместо "
            "истории вашей сессии."
        ),
        "start": (
            "В начале сессии, ДО начала любой работы, вызовите "
            "vera_session_start (CLI: `vera start`). Он вернёт "
            "текущее состояние проекта: последнюю интерпретацию кодовой базы, "
            "активные ограничения, открытые противоречия и недавние "
            "решения/изменения/нерешённые вопросы. Прочитайте это, прежде чем "
            "что-либо трогать."
        ),
        "record": (
            "Когда пользователь говорит \"Vera\", зафиксируйте это через "
            "vera_record (CLI: `vera record`). Сведите разговор к: "
            "REQUEST (что было запрошено), CHANGE (что вы сделали и в каких "
            "файлах), REASON (почему выбрана такая структура), RESULT (что "
            "произошло), STATE (ваше текущее понимание кодовой базы). Часть "
            "STATE также произнесите пользователю в своём ответе — Vera "
            "никогда не читает сам разговор, только то, что вы явно ей "
            "сообщаете."
        ),
        "protocol": [
            "Перед любой работой в новой сессии вызовите vera_session_start и прочитайте результат.",
            "Перед изменением архитектуры проверьте active_constraints и recent_decisions — не противоречьте незаметно прошлому решению.",
            "После значимого изменения вызовите vera_record с REQUEST/CHANGE/REASON/RESULT — не дожидайтесь завершения всей задачи.",
            "Различайте observation, decision, assumption и result — никогда не записывайте догадку как факт.",
            "Никогда не перезаписывайте прошлое событие. Журнал Vera по конструкции только для добавления; исправляйте вперёд, а не переписывайте историю.",
            "Если пользователь говорит \"Vera\" посреди разговора, это значит: сохраните произошедшее И объясните пользователю своё текущее понимание кодовой базы.",
            "Распознавайте \"Vera\"/\"vera\" как триггер независимо от регистра и места в сообщении (\"Vera guide\", \"vera guide\", \"открой Vera guide на немецком\" — всё подходит), а не только точное совпадение; если в сообщении назван язык, используйте его для этого вызова, иначе — текущий язык разговора по умолчанию.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · "
            "vera search <query> · vera check --action <a> · vera pause / vera resume · vera status"
        ),
        "switch": (
            "Попросите руководство на другом языке — Vera ответит на нём, "
            "например: \"Start Vera guide in German\". Поддерживаются: {langs}."
        ),
    },
    "it": {
        "tagline": "una memoria di progetto condivisa e a sola aggiunta per agenti di codice IA.",
        "core_idea": (
            "Le sessioni finiscono. Il progetto no. Claude, un modello locale "
            "o qualsiasi altro agente compatibile con MCP può riprendere "
            "esattamente da dove si era fermato l'ultimo — Claude → Vera → "
            "Local → Vera → Claude — leggendo lo stesso registro eventi "
            "invece della cronologia della sessione."
        ),
        "start": (
            "All'inizio di una sessione, chiama vera_session_start (CLI: "
            "`vera start`) PRIMA di fare qualsiasi cosa. Restituisce "
            "lo stato attuale del progetto: l'ultima interpretazione del "
            "codice, i vincoli attivi, le contraddizioni aperte e le "
            "decisioni/modifiche/questioni in sospeso recenti. Leggilo prima "
            "di toccare qualsiasi cosa."
        ),
        "record": (
            "Quando l'utente dice \"Vera\", registra il turno con vera_record "
            "(CLI: `vera record`). Distilla la conversazione in: "
            "REQUEST (cosa è stato chiesto), CHANGE (cosa hai fatto, e in "
            "quali file), REASON (perché quella struttura), RESULT (cosa è "
            "successo), STATE (la tua comprensione attuale del codice). Di' "
            "anche la parte STATE ad alta voce all'utente nella tua risposta "
            "— Vera non legge mai la conversazione, solo ciò che le dici "
            "esplicitamente."
        ),
        "protocol": [
            "Prima di qualsiasi lavoro in una nuova sessione, chiama vera_session_start e leggi il risultato.",
            "Prima di modificare l'architettura, controlla active_constraints e recent_decisions — non contraddire inconsapevolmente una decisione passata.",
            "Dopo una modifica significativa, chiama vera_record con REQUEST/CHANGE/REASON/RESULT — non aspettare che l'intero compito sia finito.",
            "Distingui observation, decision, assumption e result — non registrare mai una supposizione come se fosse un fatto.",
            "Non sovrascrivere mai un evento passato. Il registro di Vera è a sola aggiunta per progettazione; correggi in avanti, non riscrivere la storia.",
            "Quando l'utente dice \"Vera\" a metà conversazione, significa: salva ciò che è successo E spiega all'utente la tua comprensione attuale del codice.",
            "Riconosci \"Vera\"/\"vera\" come trigger indipendentemente da maiuscole/minuscole e da dove compare nel messaggio (\"Vera guide\", \"vera guide\", \"apri Vera guide in tedesco\" contano tutte), non solo una corrispondenza esatta; se il messaggio nomina una lingua, usala per quella chiamata, altrimenti usa la lingua corrente della conversazione.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · "
            "vera search <query> · vera check --action <a> · vera pause / vera resume · vera status"
        ),
        "switch": (
            "Chiedi la guida in un'altra lingua e Vera risponderà in quella "
            "lingua — es. \"Start Vera guide in German\". Lingue supportate: "
            "{langs}."
        ),
    },
    "ar": {
        "tagline": "ذاكرة مشروع مشتركة قابلة للإلحاق فقط لوكلاء البرمجة بالذكاء الاصطناعي.",
        "core_idea": (
            "الجلسات تنتهي. المشروع لا ينتهي. يمكن لـ Claude أو نموذج محلي أو "
            "أي وكيل آخر متوافق مع MCP أن يكمل تمامًا من حيث توقف الوكيل "
            "السابق — Claude ← Vera ← Local ← Vera ← Claude — عبر قراءة سجل "
            "الأحداث نفسه بدلاً من سجل الجلسة الخاص بك."
        ),
        "start": (
            "في بداية الجلسة، استدعِ vera_session_start (سطر الأوامر: `vera "
            "start`) قبل القيام بأي عمل. يُعيد الحالة الحالية "
            "للمشروع: أحدث تفسير لقاعدة الكود، القيود النشطة، التناقضات "
            "المفتوحة، والقرارات/التغييرات/المهام غير المكتملة الأخيرة. اقرأه "
            "قبل أن تلمس أي شيء."
        ),
        "record": (
            "عندما يقول المستخدم \"Vera\"، سجّل ما جرى باستخدام vera_record "
            "(سطر الأوامر: `vera record`). لخّص المحادثة إلى: REQUEST "
            "(ما طُلب)، CHANGE (ما فعلته، وأي الملفات)، REASON (لماذا اخترت "
            "هذا التصميم)، RESULT (ما الذي حدث)، STATE (فهمك الحالي لقاعدة "
            "الكود). واذكر جزء STATE أيضًا للمستخدم في ردّك — فـVera لا يقرأ "
            "المحادثة أبدًا، بل فقط ما تخبره به صراحةً."
        ),
        "protocol": [
            "قبل أي عمل في جلسة جديدة، استدعِ vera_session_start واقرأ النتيجة.",
            "قبل تغيير البنية المعمارية، تحقق من active_constraints و recent_decisions — لا تناقض قرارًا سابقًا دون علم.",
            "بعد أي تغيير مهم، استدعِ vera_record مع REQUEST/CHANGE/REASON/RESULT — لا تنتظر انتهاء المهمة كاملةً.",
            "ميّز بين observation وdecision وassumption وresult — لا تسجّل تخمينًا كأنه حقيقة.",
            "لا تستبدل حدثًا سابقًا أبدًا. سجل Vera قابل للإلحاق فقط بالتصميم؛ صحّح للأمام، ولا تعِد كتابة التاريخ.",
            "عندما يقول المستخدم \"Vera\" في منتصف المحادثة، يعني ذلك: احفظ ما حدث واشرح للمستخدم فهمك الحالي لقاعدة الكود.",
            "تعرّف على \"Vera\"/\"vera\" كمشغّل بغض النظر عن حالة الأحرف أو موضعها في الرسالة (\"Vera guide\"، \"vera guide\"، \"افتح Vera guide بالألمانية\" كلها تُحتسب)، وليس فقط عند التطابق التام؛ إذا ذكرت الرسالة لغة، استخدمها لهذا الاستدعاء، وإلا استخدم لغة المحادثة الحالية افتراضيًا.",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · "
            "vera search <query> · vera check --action <a> · vera pause / vera resume · vera status"
        ),
        "switch": (
            "اطلب الدليل بلغة أخرى وسيجيب Vera بها — مثل \"Start Vera guide in "
            "German\". اللغات المدعومة: {langs}."
        ),
    },
    "hi": {
        "tagline": "AI कोडिंग एजेंटों के लिए एक साझा, केवल-जोड़ने-योग्य प्रोजेक्ट मेमोरी।",
        "core_idea": (
            "सत्र समाप्त होते हैं। प्रोजेक्ट नहीं। Claude, कोई स्थानीय मॉडल, या कोई भी "
            "अन्य MCP-संगत एजेंट ठीक वहीं से जारी रख सकता है जहाँ पिछला रुका था — "
            "Claude → Vera → Local → Vera → Claude — आपके सत्र इतिहास के बजाय उसी "
            "इवेंट लॉग को पढ़कर।"
        ),
        "start": (
            "सत्र शुरू होते ही, कोई भी काम करने से पहले vera_session_start "
            "(CLI: `vera start`) कॉल करें। यह प्रोजेक्ट की वर्तमान स्थिति "
            "लौटाता है: कोडबेस की नवीनतम व्याख्या, सक्रिय बाध्यताएँ, खुले विरोधाभास, "
            "और हाल के निर्णय/बदलाव/अनसुलझे मुद्दे। कुछ भी छूने से पहले इसे पढ़ें।"
        ),
        "record": (
            "जब उपयोगकर्ता \"Vera\" कहे, तो vera_record (CLI: `vera "
            "record`) से उस बातचीत को दर्ज करें। बातचीत को इनमें बाँटें: REQUEST "
            "(क्या माँगा गया), CHANGE (आपने क्या किया, किन फ़ाइलों में), REASON "
            "(यह संरचना क्यों चुनी), RESULT (क्या हुआ), STATE (कोडबेस की आपकी वर्तमान "
            "समझ)। STATE वाला हिस्सा अपने जवाब में उपयोगकर्ता को भी बताएँ — Vera "
            "बातचीत को कभी नहीं पढ़ता, केवल वही जो आप उसे स्पष्ट रूप से बताते हैं।"
        ),
        "protocol": [
            "नए सत्र में कोई भी काम शुरू करने से पहले vera_session_start कॉल करें और परिणाम पढ़ें।",
            "आर्किटेक्चर बदलने से पहले active_constraints और recent_decisions जाँचें — किसी पुराने निर्णय का अनजाने में उल्लंघन न करें।",
            "किसी बड़े बदलाव के बाद, पूरा काम खत्म होने का इंतज़ार किए बिना vera_record से REQUEST/CHANGE/REASON/RESULT दर्ज करें।",
            "observation, decision, assumption और result में फ़र्क़ करें — किसी अनुमान को तथ्य की तरह दर्ज न करें।",
            "किसी पुराने इवेंट को कभी न बदलें। Vera का इवेंट लॉग डिज़ाइन से केवल-जोड़ने-योग्य है; सुधार आगे बढ़कर दर्ज करें, इतिहास को फिर से न लिखें।",
            "बातचीत के बीच में जब उपयोगकर्ता \"Vera\" कहे, इसका मतलब है: जो हुआ उसे सहेजें, और कोडबेस की अपनी वर्तमान समझ उपयोगकर्ता को समझाएँ।",
            "\"Vera\"/\"vera\" को केस या संदेश में स्थिति की परवाह किए बिना ट्रिगर के रूप में पहचानें (\"Vera guide\", \"vera guide\", \"जर्मन में Vera guide खोलो\" सभी मान्य हैं), केवल सटीक मिलान नहीं; यदि संदेश में कोई भाषा बताई गई है तो उसी में जवाब दें, अन्यथा बातचीत की मौजूदा भाषा डिफ़ॉल्ट रहे।",
        ],
        "commands": (
            "vera start · vera record · vera guide [--lang xx] · "
            "vera search <query> · vera check --action <a> · vera pause / vera resume · vera status"
        ),
        "switch": (
            "किसी अन्य भाषा में गाइड माँगें और Vera उसी में जवाब देगा — जैसे "
            "\"Start Vera guide in German\"। समर्थित भाषाएँ: {langs}।"
        ),
    },
}

_LABELS: Dict[str, Dict[str, str]] = {
    "en": {
        "header": "PROJECT CONTEXT",
        "interpretation": "Current understanding of the codebase",
        "constraints": "Active constraints",
        "contradictions": "Open contradictions",
        "decisions": "Recent decisions",
        "changes": "Recent changes",
        "unresolved": "Unresolved",
        "results": "Recent results",
        "none": "(none yet)",
        "protocol_header": "AGENT PROTOCOL (read this every session)",
    },
    "ja": {
        "header": "PROJECT CONTEXT",
        "interpretation": "コードベースの現在の解釈",
        "constraints": "有効な制約",
        "contradictions": "未解決の矛盾",
        "decisions": "直近の決定",
        "changes": "直近の変更",
        "unresolved": "未解決事項",
        "results": "直近の結果",
        "none": "（まだありません）",
        "protocol_header": "AGENT PROTOCOL（毎セッション必読）",
    },
    "zh": {
        "header": "PROJECT CONTEXT",
        "interpretation": "对代码库的当前理解",
        "constraints": "生效中的约束",
        "contradictions": "尚未解决的矛盾",
        "decisions": "最近的决策",
        "changes": "最近的变更",
        "unresolved": "未解决事项",
        "results": "最近的结果",
        "none": "（暂无）",
        "protocol_header": "AGENT PROTOCOL（每次会话必读）",
    },
    "es": {
        "header": "PROJECT CONTEXT",
        "interpretation": "Comprensión actual del código",
        "constraints": "Restricciones activas",
        "contradictions": "Contradicciones abiertas",
        "decisions": "Decisiones recientes",
        "changes": "Cambios recientes",
        "unresolved": "Pendientes",
        "results": "Resultados recientes",
        "none": "(aún ninguno)",
        "protocol_header": "AGENT PROTOCOL (leer cada sesión)",
    },
    "fr": {
        "header": "PROJECT CONTEXT",
        "interpretation": "Compréhension actuelle du code",
        "constraints": "Contraintes actives",
        "contradictions": "Contradictions ouvertes",
        "decisions": "Décisions récentes",
        "changes": "Changements récents",
        "unresolved": "En suspens",
        "results": "Résultats récents",
        "none": "(aucun pour l'instant)",
        "protocol_header": "AGENT PROTOCOL (à lire à chaque session)",
    },
    "de": {
        "header": "PROJECT CONTEXT",
        "interpretation": "Aktuelles Verständnis der Codebasis",
        "constraints": "Aktive Constraints",
        "contradictions": "Offene Widersprüche",
        "decisions": "Aktuelle Entscheidungen",
        "changes": "Aktuelle Änderungen",
        "unresolved": "Offene Punkte",
        "results": "Aktuelle Ergebnisse",
        "none": "(noch keine)",
        "protocol_header": "AGENT PROTOCOL (jede Sitzung lesen)",
    },
    "ko": {
        "header": "PROJECT CONTEXT",
        "interpretation": "코드베이스에 대한 현재 이해",
        "constraints": "활성 제약 조건",
        "contradictions": "미해결 모순",
        "decisions": "최근 결정",
        "changes": "최근 변경",
        "unresolved": "미해결 항목",
        "results": "최근 결과",
        "none": "(아직 없음)",
        "protocol_header": "AGENT PROTOCOL (매 세션 필독)",
    },
    "pt": {
        "header": "PROJECT CONTEXT",
        "interpretation": "Compreensão atual do código",
        "constraints": "Restrições ativas",
        "contradictions": "Contradições em aberto",
        "decisions": "Decisões recentes",
        "changes": "Mudanças recentes",
        "unresolved": "Pendências",
        "results": "Resultados recentes",
        "none": "(nenhum ainda)",
        "protocol_header": "AGENT PROTOCOL (ler a cada sessão)",
    },
    "ru": {
        "header": "PROJECT CONTEXT",
        "interpretation": "Текущее понимание кодовой базы",
        "constraints": "Активные ограничения",
        "contradictions": "Открытые противоречия",
        "decisions": "Недавние решения",
        "changes": "Недавние изменения",
        "unresolved": "Нерешённое",
        "results": "Недавние результаты",
        "none": "(пока нет)",
        "protocol_header": "AGENT PROTOCOL (читать каждую сессию)",
    },
    "it": {
        "header": "PROJECT CONTEXT",
        "interpretation": "Comprensione attuale del codice",
        "constraints": "Vincoli attivi",
        "contradictions": "Contraddizioni aperte",
        "decisions": "Decisioni recenti",
        "changes": "Modifiche recenti",
        "unresolved": "In sospeso",
        "results": "Risultati recenti",
        "none": "(nessuno ancora)",
        "protocol_header": "AGENT PROTOCOL (da leggere ogni sessione)",
    },
    "ar": {
        "header": "PROJECT CONTEXT",
        "interpretation": "الفهم الحالي لقاعدة الكود",
        "constraints": "القيود النشطة",
        "contradictions": "التناقضات المفتوحة",
        "decisions": "القرارات الأخيرة",
        "changes": "التغييرات الأخيرة",
        "unresolved": "غير محلول",
        "results": "النتائج الأخيرة",
        "none": "(لا يوجد بعد)",
        "protocol_header": "AGENT PROTOCOL (اقرأ في كل جلسة)",
    },
    "hi": {
        "header": "PROJECT CONTEXT",
        "interpretation": "कोडबेस की वर्तमान समझ",
        "constraints": "सक्रिय बाध्यताएँ",
        "contradictions": "खुले विरोधाभास",
        "decisions": "हाल के निर्णय",
        "changes": "हाल के बदलाव",
        "unresolved": "अनसुलझे मुद्दे",
        "results": "हाल के परिणाम",
        "none": "(अभी तक कोई नहीं)",
        "protocol_header": "AGENT PROTOCOL (हर सत्र में पढ़ें)",
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
    """Format VeraStore.get_project_state() as the PROJECT CONTEXT block a
    new session should read first, ending with the protocol reminder."""
    lang = resolve_lang(lang)
    lab = _LABELS[lang]

    def _fmt_list(items: List[Dict[str, Any]], text_key: str = "text") -> str:
        if not items:
            return f"  {lab['none']}"
        lines = []
        for it in items:
            txt = it.get(text_key) or it.get("content", "")
            author = it.get("author", it.get("source", ""))
            tag = f" [{author}]" if author else ""
            files = it.get("files")
            file_tag = f" ({', '.join(files)})" if files else ""
            lines.append(f"  - {txt}{file_tag}{tag}")
        return "\n".join(lines)

    interp = state.get("interpretation")
    interp_line = f"  {interp['content']} [{interp['author']}]" if interp else f"  {lab['none']}"

    parts = [
        lab["header"],
        "",
        f"{lab['interpretation']}:",
        interp_line,
        "",
        f"{lab['constraints']}:",
        _fmt_list(state.get("active_constraints", [])),
        "",
        f"{lab['contradictions']}:",
        _fmt_list(state.get("open_contradictions", []), text_key="constraint"),
        "",
        f"{lab['decisions']}:",
        _fmt_list(state.get("recent_decisions", [])),
        "",
        f"{lab['changes']}:",
        _fmt_list(state.get("recent_changes", [])),
        "",
        f"{lab['unresolved']}:",
        _fmt_list(state.get("recent_unresolved", [])),
        "",
        f"{lab['results']}:",
        _fmt_list(state.get("recent_results", [])),
        "",
        render_protocol(lang),
    ]
    return "\n".join(parts)
