// 설정 화면
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Item {
    id: sp
    property color accent: "#3ee6ff"
    property bool open: false
    property var cfg: ({})
    visible: opacity > 0
    opacity: open ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 200 } }

    readonly property var brains: [
        { v: "pro", t: "Claude Pro 계정 (추가 비용 없음)" },
        { v: "api", t: "Claude API 키 (사용량 과금)" },
        { v: "local", t: "로컬 전용 — Claude 사용 안 함 (토큰 0)" }
    ]
    readonly property bool isLocal: brainBox.currentIndex === 2
    readonly property var proModels: [
        { v: "haiku", t: "Haiku — 가장 빠름 (기본)" },
        { v: "sonnet", t: "Sonnet — 더 똑똑함, 조금 느림" },
        { v: "opus", t: "Opus — 가장 똑똑함, Pro 한도 빨리 소모" }
    ]
    readonly property bool isPro: brainBox.currentIndex === 0
    readonly property var localModels: [
        { v: "qwen2.5:1.5b", t: "Qwen 2.5 1.5B — 빠름·정확 (기본)" },
        { v: "qwen2.5:3b", t: "Qwen 2.5 3B — 느림, 일부 표현은 더 잘 이해" }
    ]
    readonly property var models: [
        { v: "claude-opus-5-5", t: "Claude Opus 5.5 — 가장 똑똑함 (기본)" },
        { v: "claude-sonnet-5-5", t: "Claude Sonnet 5.5 — 빠르고 균형" },
        { v: "claude-haiku-5-5", t: "Claude Haiku 5.5 — 가장 빠름·저렴" }
    ]
    readonly property var efforts: [
        { v: "low", t: "빠르게 (low)" }, { v: "medium", t: "보통 (medium)" }, { v: "high", t: "깊게 (high)" }
    ]
    readonly property var sttEngines: [
        { v: "auto", t: "자동 — 대기 중엔 오프라인, 부른 뒤엔 Google (기본)" },
        { v: "local", t: "오프라인 전용 — 소리가 PC 밖으로 안 나감" },
        { v: "google", t: "Google 전용 — 가장 정확, 인터넷 필요" }
    ]
    readonly property var voices: [
        { v: "ko-KR-InJoonNeural", t: "인준 — 남성 · 자비스 (기본)" },
        { v: "ko-KR-HyunsuMultilingualNeural", t: "현수 — 남성" },
        { v: "ko-KR-SunHiNeural", t: "선희 — 여성" }
    ]

    function show() {
        cfg = JSON.parse(jarvis.settingsJson())
        keyField.text = ""
        titleField.text = cfg.user_title || ""
        cityField.text = cfg.home_city || ""
        hotkeyField.text = cfg.hotkey || ""
        brainBox.currentIndex = cfg.brain === "api" ? 1 : cfg.brain === "local" ? 2 : 0
        localSw.checked = cfg.local_first !== false
        localAiSw.checked = cfg.local_ai !== false
        localAiBox.currentIndex = Math.max(0, localModels.findIndex(m => m.v === cfg.local_ai_model))
        modelBox.currentIndex = Math.max(0, models.findIndex(m => m.v === cfg.model))
        proModelBox.currentIndex = Math.max(0, proModels.findIndex(m => m.v === cfg.pro_model))
        effortBox.currentIndex = Math.max(0, efforts.findIndex(m => m.v === cfg.effort))
        voiceBox.currentIndex = Math.max(0, voices.findIndex(m => m.v === cfg.tts_voice))
        fxSw.checked = cfg.voice_fx !== false
        wakeSw.checked = !!cfg.wake_word_enabled
        bargeSw.checked = cfg.barge_in !== false
        searchSw.checked = !!cfg.web_search
        approveSw.checked = !!cfg.auto_approve
        sens.value = cfg.mic_sensitivity || 1.0
        noiseSw.checked = cfg.noise_robust !== false
        beamSw.checked = cfg.beamforming !== false
        agcSw.checked = cfg.agc !== false
        sttBox.currentIndex = Math.max(0, sttEngines.findIndex(m => m.v === cfg.stt_engine))
        lockSw.checked = cfg.speaker_lock !== false
        ownerSw.checked = !!cfg.owner_only && jarvis.voiceEnrolled
        strict.value = cfg.speaker_threshold || 0.40
        askSw.checked = cfg.speaker_ask_borderline !== false
        proSw.checked = cfg.proactive !== false
        briefSw.checked = cfg.daily_briefing !== false
        remindSw.checked = cfg.todo_reminders !== false
        eventSw.checked = cfg.event_reminders !== false
        icalField.text = ""
        mailUserField.text = cfg.mail_user || ""
        mailPwField.text = ""
        delBtn.armed = false
        open = true
    }
    function save() {
        const out = {
            user_title: titleField.text.trim() || "주인님",
            home_city: cityField.text.trim() || "Seoul",
            hotkey: hotkeyField.text.trim().toLowerCase() || "ctrl+alt+j",
            brain: brains[brainBox.currentIndex].v,
            local_first: localSw.checked,
            local_ai: localAiSw.checked,
            local_ai_model: localModels[localAiBox.currentIndex].v,
            pro_model: proModels[proModelBox.currentIndex].v,
            model: models[modelBox.currentIndex].v,
            effort: efforts[effortBox.currentIndex].v,
            tts_voice: voices[voiceBox.currentIndex].v,
            voice_fx: fxSw.checked,
            wake_word_enabled: wakeSw.checked,
            barge_in: bargeSw.checked,
            web_search: searchSw.checked,
            auto_approve: approveSw.checked,
            mic_sensitivity: Math.round(sens.value * 10) / 10,
            noise_robust: noiseSw.checked,
            beamforming: beamSw.checked,
            agc: agcSw.checked,
            stt_engine: sttEngines[sttBox.currentIndex].v,
            speaker_lock: lockSw.checked,
            owner_only: ownerSw.checked,
            speaker_threshold: Math.round(strict.value * 100) / 100,
            speaker_ask_borderline: askSw.checked,
            proactive: proSw.checked,
            daily_briefing: briefSw.checked,
            todo_reminders: remindSw.checked,
            event_reminders: eventSw.checked,
            mail_user: mailUserField.text.trim()
        }
        if (icalField.text.trim() !== "") out.calendar_ical_url = icalField.text.trim()
        if (mailPwField.text.trim() !== "") out.mail_app_password = mailPwField.text.trim()
        if (keyField.text.trim() !== "") out.anthropic_api_key = keyField.text.trim()
        jarvis.saveSettings(JSON.stringify(out))
        open = false
    }

    component Label2: Text {
        color: Qt.rgba(sp.accent.r, sp.accent.g, sp.accent.b, 0.8)
        font.family: "Bahnschrift"; font.pixelSize: 10; font.letterSpacing: 1.5
        Layout.topMargin: 4
    }
    component Field: TextField {
        Layout.fillWidth: true
        color: "#e6fbff"
        placeholderTextColor: Qt.rgba(0.7, 0.9, 1, 0.35)
        selectionColor: Qt.rgba(sp.accent.r, sp.accent.g, sp.accent.b, 0.5)
        font.pixelSize: 12
        leftPadding: 8
        background: Rectangle {
            implicitHeight: 30
            color: Qt.rgba(0, 0.05, 0.08, 0.7)
            border.color: parent.activeFocus ? sp.accent : Qt.rgba(sp.accent.r, sp.accent.g, sp.accent.b, 0.3)
            radius: 3
        }
    }
    component Combo: ComboBox {
        id: cb
        Layout.fillWidth: true
        textRole: "t"
        font.pixelSize: 12
        palette.buttonText: "#e6fbff"
        palette.text: "#e6fbff"
        palette.window: "#06202b"
        palette.base: "#06202b"
        palette.highlight: Qt.rgba(sp.accent.r, sp.accent.g, sp.accent.b, 0.35)
        palette.highlightedText: "#ffffff"
        palette.light: "#0a2f3c"
        palette.midlight: "#0a2f3c"
        palette.mid: "#0a2f3c"
        palette.dark: sp.accent
        palette.button: Qt.rgba(0, 0.05, 0.08, 0.7)
        background: Rectangle {
            implicitHeight: 30
            color: Qt.rgba(0, 0.05, 0.08, 0.7)
            border.color: cb.activeFocus || cb.popup.visible ? sp.accent : Qt.rgba(sp.accent.r, sp.accent.g, sp.accent.b, 0.3)
            radius: 3
        }
    }
    component HSlider: Slider {
        id: sl
        Layout.fillWidth: true
        background: Rectangle {
            x: sl.leftPadding
            y: sl.topPadding + sl.availableHeight / 2 - height / 2
            width: sl.availableWidth; height: 3; radius: 1.5
            color: Qt.rgba(sp.accent.r, sp.accent.g, sp.accent.b, 0.2)
            Rectangle { width: sl.visualPosition * parent.width; height: parent.height; radius: 1.5; color: sp.accent }
        }
        handle: Rectangle {
            x: sl.leftPadding + sl.visualPosition * (sl.availableWidth - width)
            y: sl.topPadding + sl.availableHeight / 2 - height / 2
            width: 14; height: 14; radius: 7
            color: "#06202b"
            border.color: sp.accent; border.width: 2
        }
    }
    component Hint: Text {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: Qt.rgba(0.75, 0.93, 1, 0.5)
        font.pixelSize: 10
    }
    component Toggle: Switch {
        id: sw
        font.pixelSize: 12
        palette.windowText: "#e6fbff"
        indicator: Rectangle {
            implicitWidth: 34; implicitHeight: 16; radius: 8
            x: sw.width - width - sw.rightPadding
            y: (sw.height - height) / 2
            color: sw.checked ? Qt.rgba(sp.accent.r, sp.accent.g, sp.accent.b, 0.35) : Qt.rgba(1, 1, 1, 0.06)
            border.color: sw.checked ? sp.accent : Qt.rgba(sp.accent.r, sp.accent.g, sp.accent.b, 0.35)
            Rectangle {
                width: 10; height: 10; radius: 5; y: 3
                x: sw.checked ? parent.width - width - 3 : 3
                color: sw.checked ? "#ffffff" : Qt.rgba(sp.accent.r, sp.accent.g, sp.accent.b, 0.6)
                Behavior on x { NumberAnimation { duration: 120 } }
            }
        }
        contentItem: Text {
            text: sw.text; color: "#d8f6ff"; font.pixelSize: 12
            verticalAlignment: Text.AlignVCenter
            rightPadding: sw.indicator.width + 8
        }
        Layout.fillWidth: true
    }

    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0.02, 0.04, 0.6); radius: 6 }
    MouseArea { anchors.fill: parent; onClicked: sp.open = false }

    HoloPanel {
        accent: sp.accent
        title: "SYSTEM CONFIGURATION"
        tag: "v1.0"
        anchors.fill: parent
        anchors.margins: 12
        fillAlpha: 0.94
        MouseArea { anchors.fill: parent }  // 패널 내부 클릭은 닫히지 않게

        ScrollView {
            id: scroll
            anchors.fill: parent
            anchors.bottomMargin: 44
            contentWidth: availableWidth
            clip: true

            ColumnLayout {
                width: scroll.availableWidth - 6
                spacing: 4

                Label2 { text: "AI CONNECTION" }
                Combo { id: brainBox; model: sp.brains }
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: Qt.rgba(0.75, 0.93, 1, 0.5)
                    font.pixelSize: 10
                    text: sp.isPro ? "이 PC에 설치된 Claude Code의 Pro 로그인을 사용합니다. 사용량은 Pro 한도에서 차감됩니다."
                        : sp.isLocal ? "앱 실행·볼륨·음악·유튜브·검색·날씨·타이머 등 기본 명령만 처리합니다. 대화와 복잡한 작업은 할 수 없습니다."
                        : "console.anthropic.com 에서 발급한 키를 사용합니다. 쓴 만큼 과금됩니다."
                }
                Toggle {
                    id: localSw
                    visible: !sp.isLocal
                    text: "로컬 우선 — 기본 명령은 토큰 없이 즉시 처리"
                }
                Toggle {
                    id: localAiSw
                    visible: localSw.checked || sp.isLocal
                    text: "로컬 AI — 말을 바꿔 해도 내 PC의 AI가 이해 (토큰 0, Ollama)"
                }
                Combo { id: localAiBox; visible: localAiSw.visible && localAiSw.checked; model: sp.localModels }
                Label2 { visible: !sp.isPro && !sp.isLocal; text: "CLAUDE API KEY" }
                Field {
                    id: keyField
                    visible: !sp.isPro && !sp.isLocal
                    echoMode: TextInput.Password
                    placeholderText: sp.cfg.has_api_key ? ("등록됨 " + (sp.cfg.api_key_hint || "") + " — 바꾸려면 입력") : "sk-ant-… (console.anthropic.com 에서 발급)"
                }
                Label2 { visible: !sp.isLocal; text: "AI MODEL" }
                Combo { id: proModelBox; visible: sp.isPro; model: sp.proModels }
                Combo { id: modelBox; visible: !sp.isPro && !sp.isLocal; model: sp.models }
                Label2 { text: "RESPONSE DEPTH" }
                Combo { id: effortBox; model: sp.efforts }
                Label2 { text: "VOICE" }
                Combo { id: voiceBox; model: sp.voices }
                Toggle { id: fxSw; text: "자비스 음색 (깨끗하게 다듬은 디지털 목소리)" }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    ColumnLayout {
                        Layout.fillWidth: true
                        Label2 { text: "호칭" }
                        Field { id: titleField; placeholderText: "주인님" }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        Label2 { text: "기본 도시 (날씨)" }
                        Field { id: cityField; placeholderText: "Seoul" }
                    }
                }
                Label2 { text: "GLOBAL HOTKEY" }
                Field { id: hotkeyField; placeholderText: "ctrl+alt+j" }
                Label2 { text: "MIC SENSITIVITY  ·  " + sens.value.toFixed(1) }
                HSlider { id: sens; from: 0.5; to: 3.0; stepSize: 0.1 }
                Toggle { id: noiseSw; text: "소음 환경 모드 (시끄러운 곳에서 작은 목소리)" }
                Toggle { id: beamSw; text: "빔포밍 (정면 목소리 강조 · 마이크 2개 이상)" }
                Toggle { id: agcSw; text: "자동 음량 조절 (멀리서 말해도 키워서 듣기)" }
                Hint { text: sp.cfg.mic_status || ""; font.pixelSize: 11 }
                Label2 { text: "SPEECH RECOGNITION  ·  음성 인식" }
                Combo { id: sttBox; model: sp.sttEngines }
                Hint { text: sp.cfg.stt_status || ""; font.pixelSize: 11 }
                Toggle { id: wakeSw; text: "“자비스” 호출어 상시 대기" }
                Toggle { id: bargeSw; text: "말 끊기 — 말하는 도중 “그만” · “자비스, …”로 멈추기" }

                Label2 { text: "VOICE ID  ·  화자 인식"; Layout.topMargin: 10 }
                Hint {
                    text: jarvis.voiceStatus
                    color: jarvis.voiceEnrolled ? Qt.rgba(0.6, 1, 0.8, 0.85) : Qt.rgba(0.75, 0.93, 1, 0.6)
                    font.pixelSize: 11
                }
                RowLayout {
                    spacing: 8
                    HoloButton {
                        text: jarvis.voiceEnrolled ? "다시 등록" : "목소리 등록"
                        accent: sp.accent
                        primary: !jarvis.voiceEnrolled
                        onClicked: { sp.save(); jarvis.startEnroll() }
                    }
                    HoloButton {
                        id: delBtn
                        property bool armed: false
                        visible: jarvis.voiceEnrolled
                        text: armed ? "정말 삭제" : "삭제"
                        accent: armed ? "#ff6b81" : sp.accent
                        onClicked: {
                            if (!armed) { armed = true; return }
                            armed = false
                            ownerSw.checked = false
                            jarvis.clearVoice()
                        }
                    }
                }
                Toggle {
                    id: ownerSw
                    enabled: jarvis.voiceEnrolled
                    opacity: enabled ? 1 : 0.45
                    text: "등록된 주인 목소리에만 반응"
                }
                Toggle { id: lockSw; text: "부른 사람의 목소리만 이어서 인식 (세션 잠금)" }
                Label2 { text: "판별 엄격도  ·  " + strict.value.toFixed(2) + (strict.value < 0.34 ? "  (느슨함)" : strict.value > 0.48 ? "  (엄격함)" : "") }
                HSlider { id: strict; from: 0.25; to: 0.60; stepSize: 0.01 }
                Toggle { id: askSw; text: "목소리가 애매하면 실행 전에 “부르셨습니까?” 되묻기" }
                Hint {
                    text: "본인 명령이 자주 무시되면 낮추고, 다른 사람 말에 반응하면 높이세요. "
                        + "목소리 정보는 data/voice_profile.json 에만 저장되고 외부로 보내지 않습니다."
                }

                Toggle { id: searchSw; text: "Claude 웹 검색 사용 (최신 정보)" }
                Toggle { id: approveSw; text: "위험 명령 자동 승인 (권장하지 않음)" }
                Toggle { id: proSw; text: "먼저 말 걸기 (배터리 부족 · 할 일 마감 알림)" }
                Toggle { id: briefSw; enabled: proSw.checked; opacity: enabled ? 1 : 0.45; text: "아침 첫 사용 때 브리핑 (날짜 · 날씨 · 오늘 할 일)" }
                Toggle { id: remindSw; enabled: proSw.checked; opacity: enabled ? 1 : 0.45; text: "할 일 마감 알림 (당일 오전 9시 · 전날 저녁 7시)" }
                Toggle { id: eventSw; enabled: proSw.checked; opacity: enabled ? 1 : 0.45; text: "일정 시작 전 알림 (기본 10분 전 · 캘린더 연결 시)" }
                Hint { text: "밤 11시~아침 7시에는 소리 내어 말하지 않고 화면 알림만 띄웁니다 (data/config.json 의 quiet_hours)." }
                Label2 { text: "CALENDAR · MAIL (읽기 전용)" }
                Field {
                    id: icalField
                    echoMode: TextInput.Password
                    placeholderText: sp.cfg.has_calendar ? "캘린더 연결됨 — 바꾸려면 새 주소, 끊으려면 ‘해제’ 입력"
                                                         : "구글 캘린더 비공개 iCal 주소 (https://…/basic.ics)"
                }
                Field { id: mailUserField; placeholderText: "메일 주소 (예: name@gmail.com · 학교 계정이면 학교 메일 주소)" }
                Field {
                    id: mailPwField
                    echoMode: TextInput.Password
                    placeholderText: sp.cfg.has_mail ? "앱 비밀번호 등록됨 — 바꾸려면 입력, 끊으려면 ‘해제’ 입력"
                                                     : "메일 앱 비밀번호 (구글 계정 → 보안 → 2단계 인증 → 앱 비밀번호)"
                }
                Hint {
                    text: "iCal 주소: 구글 캘린더 → 설정 → 내 캘린더 → 캘린더 통합 → ‘비공개 주소(iCal 형식)’. "
                        + "주소와 비밀번호는 Windows 암호화로 이 PC 에만 저장되고, 일정은 읽기만, 메일은 안 읽은 메일의 보낸 사람 · 제목만 봅니다. "
                        + "앱 비밀번호를 만들 수 없는 학교 계정은 메일 주소만 적어 두세요 — “클래스룸 정리해 줘” 가 크롬의 그 계정 지메일에서 클래스룸 알림을 읽습니다."
                }
                Text {
                    Layout.fillWidth: true
                    Layout.topMargin: 6
                    wrapMode: Text.WordWrap
                    color: Qt.rgba(0.75, 0.93, 1, 0.45)
                    font.pixelSize: 10
                    text: "설정은 data/config.json 에 저장됩니다. API 키 대신 ANTHROPIC_API_KEY 환경변수를 써도 됩니다."
                }
            }
        }
        Row {
            anchors.bottom: parent.bottom
            anchors.right: parent.right
            spacing: 8
            HoloButton { text: "새 대화"; accent: sp.accent; onClicked: { jarvis.clearConversation(); sp.open = false } }
            HoloButton { text: "취소"; accent: sp.accent; onClicked: sp.open = false }
            HoloButton { text: "저장"; accent: sp.accent; primary: true; onClicked: sp.save() }
        }
    }
}
