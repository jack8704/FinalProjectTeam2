package com.aixlab.app

import ai.pleos.playground.tts.TextToSpeech                     // ★ Pleos TTS SDK (안드로이드 기본 TTS 아님)
import ai.pleos.playground.tts.constant.ErrorType
import ai.pleos.playground.tts.constant.Mode
import ai.pleos.playground.tts.listener.EventListener
import ai.pleos.playground.tts.listener.OnInitializeListener
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import androidx.compose.runtime.mutableStateOf
import androidx.core.app.NotificationCompat
import org.json.JSONArray
import java.util.Locale

/**
 * SoloM 안내 음성 서비스
 *  - 서버 /guidance 를 1초마다 확인 → 새 안내를 Pleos TTS SDK 로 읽음
 *  - Foreground Service 로 실행 → 다른 앱(내비 등)이 앞에 있어도 꺼지지 않음 (상단 알림 표시)
 *  - 에뮬레이터에는 안드로이드 기본 TTS 엔진이 연결되지 않아(status=-1) 기존 TTS 앱과 같은 Pleos SDK 사용
 */
class GuidanceService : Service() {

    companion object {
        const val SERVER = "http://10.0.2.2:8000"                  // 에뮬레이터 → PC(com1) → portproxy → com2 서버
        const val POLL_MS = 1000L                                 // 확인 간격
        private const val CHANNEL_ID = "codriver_guidance"         // 채널 ID는 내부용이라 그대로 둠
        private const val NOTI_ID = 1
        private const val TAG = "CODRIVER_TTS"
        val lastText = mutableStateOf("안내 대기 중")               // 앱 화면에 표시할 마지막 안내 (Compose가 자동 갱신)
    }

    private val main = Handler(Looper.getMainLooper())            // TTS 호출은 메인 스레드에서
    private var tts: TextToSpeech? = null
    private var ttsReady = false                                  // TTS 준비 완료 여부
    private var speaking = false                                  // 지금 읽는 중인지
    private val queue = ArrayDeque<String>()                      // 읽을 안내 대기열 (앞 안내를 끊지 않기 위해)
    @Volatile private var running = true                          // 폴링 스레드 종료 신호
    private var lastId = -1                                       // 마지막으로 읽은 안내 번호 (-1 = 아직 시작 전)

    override fun onCreate() {
        super.onCreate()
        startAsForeground()                                       // 5초 안에 반드시 호출해야 함
        initTts()
        Thread { pollLoop() }.start()                             // 서버 확인은 별도 스레드
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY   // 시스템이 꺼도 다시 시작

    override fun onBind(intent: Intent?): IBinder? = null

    // ───────── Foreground Service 시작 (상단 알림) ─────────
    private fun startAsForeground() {
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "SoloM 안내", NotificationManager.IMPORTANCE_LOW)   // 소리 없는 알림
            )
        }
        val noti: Notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("SoloM")
            .setContentText("교통법규 음성 안내 동작 중")
            .setSmallIcon(R.mipmap.ic_launcher)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTI_ID, noti, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK)   // 서비스 종류 지정
        } else {
            startForeground(NOTI_ID, noti)                                                   // 옛 버전 방식
        }
    }

    // ───────── Pleos TTS 이벤트 (읽기 시작·끝) ─────────
    private val listener = object : EventListener {
        override fun onReady() = Unit
        override fun onStart() { Log.d(TAG, "읽기 시작") }
        override fun onUpdatedRms(rms: Double) = Unit
        override fun onDone() { Log.d(TAG, "읽기 완료"); speakNext() }            // 끝나면 다음 안내
        override fun onStop() { speakNext() }
        override fun onError(errorType: ErrorType) { Log.e(TAG, "재생 오류: $errorType"); speakNext() }
    }

    // ───────── TTS 준비 (기존 TTS 앱과 같은 방식) ─────────
    private fun initTts() {
        tts = TextToSpeech(applicationContext, Mode.ON_DEVICE)    // 등록 필요 없는 모드
        tts?.initialize(object : OnInitializeListener {
            override fun onSuccess() {
                tts?.addEventListener(listener)                   // 초기화 후 리스너 등록
                tts?.setLocale(Locale.KOREA)                      // 한국어
                ttsReady = true
                Log.d(TAG, "TTS 준비 완료 (Pleos ON_DEVICE)")
                main.post { speakNext() }                         // 준비 전에 쌓인 안내 읽기
            }
            override fun onFailure(errorType: ErrorType) {
                Log.e(TAG, "TTS 초기화 실패: $errorType")
            }
        })
    }

    /** 안내를 대기열에 넣고, 읽는 중이 아니면 바로 읽기 (메인 스레드에서 실행) */
    private fun speak(text: String) = main.post {
        queue.addLast(text)
        if (!speaking) speakNext()
    }

    /** 대기열의 다음 안내 읽기 */
    private fun speakNext() {
        if (!ttsReady) return                                     // 준비 전이면 대기 (onSuccess에서 다시 호출)
        val next = queue.removeFirstOrNull()
        if (next == null) { speaking = false; return }
        speaking = true
        tts?.speak(next)
    }

    // ───────── 서버 확인 반복 ─────────
    private fun pollLoop() {
        while (running) {
            try {
                val after = if (lastId < 0) 0 else lastId
                val conn = java.net.URL("$SERVER/guidance?after=$after").openConnection() as java.net.HttpURLConnection
                conn.connectTimeout = 3000
                conn.readTimeout = 3000
                val body = conn.inputStream.bufferedReader().readText()
                conn.disconnect()
                val arr = JSONArray(body)
                if (lastId < 0) {                                  // 첫 확인: 이미 쌓인 옛 안내는 읽지 않고 번호만 기억
                    lastId = (0 until arr.length()).maxOfOrNull { arr.getJSONObject(it).getInt("id") } ?: 0
                    Log.d(TAG, "안내 확인 시작 (#$lastId 이후)")
                } else {
                    for (i in 0 until arr.length()) {
                        val g = arr.getJSONObject(i)
                        lastId = g.getInt("id")
                        val text = g.getString("text")
                        Log.d(TAG, "안내 #$lastId ${g.optString("code")} → $text")
                        lastText.value = text                       // 화면 표시
                        speak(text)
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "안내 확인 실패: ${e.message}")          // 서버 꺼짐 등 → 다음 주기에 재시도
            }
            Thread.sleep(POLL_MS)
        }
    }

    override fun onDestroy() {
        running = false
        tts?.removeEventListener(listener)                        // 리스너 해제
        tts?.release()                                            // Pleos TTS 자원 반납
        super.onDestroy()
    }
}