package com.aixlab.app

import ai.pleos.playground.navi.constants.NaviErrorCode
import ai.pleos.playground.navi.constants.NavigationStatus
import ai.pleos.playground.navi.data.CameraAlert
import ai.pleos.playground.navi.data.CautionPoint
import ai.pleos.playground.navi.data.CurrentLocationInfo
import ai.pleos.playground.navi.data.DestinationArrivedInfo
import ai.pleos.playground.navi.data.DrivingInfo
import ai.pleos.playground.navi.data.RouteStartInfo
import ai.pleos.playground.navi.data.RouteStateInfo
import ai.pleos.playground.navi.data.TBTInfo
import ai.pleos.playground.navi.helper.NaviHelper
import ai.pleos.playground.navi.helper.listener.NaviHelperEventListener
import ai.pleos.playground.vehicle.Vehicle
import ai.pleos.playground.vehicle.api.model.area.DoorArea
import ai.pleos.playground.vehicle.api.model.telltale.Telltales
import ai.pleos.playground.vehicle.constant.area.DoorValue
import ai.pleos.playground.vehicle.constant.area.TurnSignalValue
import ai.pleos.playground.vehicle.constant.control.VehicleGear
import ai.pleos.playground.vehicle.listener.DoorPositionListener
import ai.pleos.playground.vehicle.listener.GearSelectionListener       // ★ 추가: 기어 리스너
import ai.pleos.playground.vehicle.listener.TelltaleInfoListener
import ai.pleos.playground.vehicle.listener.TurnSignalStateListener
import android.car.Car                                                  // AAOS Car API (차속)
import android.car.VehiclePropertyIds
import android.car.hardware.CarPropertyValue
import android.car.hardware.property.CarPropertyManager
import android.content.Intent                                           // ★ 11/10 추가: 안내 서비스 시작
import android.content.pm.PackageManager                                // 권한 확인
import androidx.compose.foundation.layout.Column                        // ★ 11/10 추가: 화면 구성
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp                                      // 글자 크기 단위
import androidx.compose.ui.text.font.FontWeight                         // 글자 굵기
import androidx.compose.ui.graphics.Color                               // 글자 색
import androidx.compose.foundation.rememberScrollState                  // 글이 길면 스크롤
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Box                           // 가운데 정렬용 바깥 상자
import androidx.compose.ui.Alignment                                    // 정렬 기준
import androidx.compose.ui.text.style.TextAlign                         // 글자 가운데 정렬
import androidx.core.content.ContextCompat
import android.location.Location                                        // 위치
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import com.aixlab.app.ui.theme.CoDriverTheme

class MainActivity : ComponentActivity() {

    private lateinit var vehicle: Vehicle                 // Pleos Vehicle 객체 (onDestroy에서 해제)
    private var car: Car? = null                          // AAOS Car 서비스 (차속용)
    private var lastSentSpeed = -1                        // 같은 차속 반복 전송 방지

    private var lastSpeedLimit = -1

    // 방향지시등 실시간 리스너 (Pleos)
    private val turnSignalListener = object : TurnSignalStateListener {
        override fun onTurnSignalStateUpdated(state: TurnSignalValue?) {
            Log.d("PLEOS", "방향지시등 변경 → $state")
            sendSignal("turn_signal", state.toString())
        }

        override fun onFailed(e: Exception) {
            Log.e("PLEOS", "방향지시등 리스너 오류", e)
        }
    }

    // ★ 추가: 기어 실시간 리스너 (Pleos)
    // 👉 object에 커서 → Alt+Enter → Implement members 로 메서드 자동 생성 후 내용 채우기
    // 기어 실시간 리스너 (Pleos)
    private val gearListener = object : GearSelectionListener {
        override fun onSelected(gear: VehicleGear?) {
            Log.d("PLEOS", "기어 변경 → $gear")          // 기어가 바뀔 때마다 로그 (GEAR_PARK / GEAR_DRIVE 등)
            sendSignal("gear", gear.toString())            // 서버로 전송
        }

        override fun onFailed(e: Exception) {
            Log.e("PLEOS", "기어 리스너 오류", e)          // 감지 실패 시 원인 출력
        }
    }
    private val telltaleListener = object : TelltaleInfoListener {   // 텔테일 실시간 리스너
        override fun onTelltaleInfoUpdated(telltales: Telltales?) {
            // 값을 받는 메서드 (이름은 IDE가 만든 그대로 둠)
            Log.d("PLEOS", "텔테일 변경 → $telltales")         // 파라미터 이름이 다르면 그 이름으로 바꿈
            sendSignal("telltales", telltales.toString())         // 서버로 전송
        }

        override fun onFailed(e: Exception) {
            Log.e("PLEOS", "텔테일 리스너 오류", e)
        }

    }
    private val doorAreas = mapOf(
        "door_fl" to DoorValue.ROW_1_LEFT,     // 운전석
        "door_fr" to DoorValue.ROW_1_RIGHT,    // 조수석
        "door_rl" to DoorValue.ROW_2_LEFT,     // 뒷좌석 왼쪽
        "door_rr" to DoorValue.ROW_2_RIGHT,    // 뒷좌석 오른쪽
        "frunk" to DoorValue.HOOD,           // 프렁크 (앞 트렁크)
        "trunk" to DoorValue.REAR            // 트렁크
    )

    // 문마다 리스너 1개씩 생성 (콜백에 어느 문인지 정보가 없어서 이름을 미리 묶어 둠)
    private val doorListeners = doorAreas.mapValues { (name, _) ->
        object : DoorPositionListener {
            override fun onPositionUpdated(pos: Int?) {
                Log.d("PLEOS", "$name 위치 변경 → $pos")        // 0 = 닫힘, 0보다 크면 열림 (추정)
                sendSignal(name, pos.toString())                 // 서버로 전송
            }

            override fun onFailed(e: Exception) {
                Log.e("PLEOS", "$name 리스너 오류", e)            // 미지원 문이면 여기 찍힘
            }
        }
    }
    private val naviLastTime = mutableMapOf<String, Long>()     // 콜백별 직전 수신 시각
    private val naviCount = mutableMapOf<String, Int>()         // 콜백별 수신 횟수

    // 내비 콜백이 올 때마다 호출 → 몇 번째인지, 직전과 몇 ms 간격인지 로그
    private fun logGap(name: String, info: String = "") {
        val now = System.currentTimeMillis()
        val gap = naviLastTime[name]?.let { now - it } ?: 0L     // 처음이면 0
        naviLastTime[name] = now
        val n = (naviCount[name] ?: 0) + 1
        naviCount[name] = n
        Log.d("NAVI_GAP", "$name #$n 간격 ${gap}ms $info")     // 별도 태그로 분리
    }

    private val handler =
        android.os.Handler(android.os.Looper.getMainLooper())   // 주기 실행용 (이미 있으면 이 줄 생략)
    private var lastNextTurn =
        ""                                                    // 직전 다음 회전 (같으면 서버 전송 생략)

    // 내비 정보 1초마다 요청 → 결과는 naviListener 콜백으로 돌아옴
    private val naviPoll = object : Runnable {
        override fun run() {
            naviHelper.getTBTInfo()                                                  // → onTBTInfo
            naviHelper.getRouteStateInfo()                                           // → onRouteStateInfo
            handler.postDelayed(this, 1000)                                          // 1초 뒤 반복
        }
    }
    private lateinit var naviHelper: NaviHelper                     // Pleos 내비 SDK 객체
    private val naviListener = object : NaviHelperEventListener {   // 내비 이벤트 리스너 (필요한 것만 재정의)
        override fun onCurrentRoadSpeedLimit(speedLimit: Int) {                         // 현재 도로 제한속도
            logGap("speedLimit", "값=$speedLimit")
            if (speedLimit == lastSpeedLimit) return                                     //
            lastSpeedLimit = speedLimit                                                  //
            Log.d("PLEOS", "제한속도 = $speedLimit"); sendSignal(
                "navi_speed_limit",
                speedLimit.toString()
            )
        }

        override fun onCautionPointInfo(cautionPointList: List<CautionPoint>) {         // 주의 지점 (보호구역 등)
            Log.d("PLEOS", "주의지점 = $cautionPointList"); sendSignal(
                "navi_caution",
                cautionPointList.toString()
            )
        }

        override fun onCameraAlert(cameraAlertList: List<CameraAlert>) {                // 단속 카메라
            Log.d("PLEOS", "카메라 = $cameraAlertList"); sendSignal(
                "navi_camera",
                cameraAlertList.toString()
            )
        }

        override fun onTBTInfo(tbtInfoList: List<TBTInfo>) {                            // 다음 회전 안내 (요청 결과)
            val first =
                tbtInfoList.firstOrNull()                                        // 첫 항목 = 다음 회전
            logGap("tbt", "다음=${first?.type} ${first?.distance}m")
            val now = "${first?.type},${first?.distance}"
            if (now == lastNextTurn) return                                              // 바뀌지 않았으면 서버 전송 생략
            lastNextTurn = now
            sendSignal(
                "navi_next_turn",
                now
            )                                            // 예: TURN_LEFT,80.0
        }

        override fun onRouteStateInfo(routeStateInfo: RouteStateInfo) {                  // 경로 진행 상태 (요청 결과)
            logGap("routeState", "모드=${routeStateInfo.naviMode}")                      // 안내 중 여부만 기록
        }


        override fun onCurrentLocationInfo(currentLocationInfo: CurrentLocationInfo) {  // 현재 위치·도로 정보
            logGap("location")
            Log.d("PLEOS", "내비 위치 = $currentLocationInfo"); sendSignal(
                "navi_location",
                currentLocationInfo.toString()
            )
        }

        override fun onDrivingInfo(drivingInfo: DrivingInfo) {                          // 주행 정보
            logGap("driving")
            Log.d("PLEOS", "주행정보 = $drivingInfo"); sendSignal(
                "navi_driving",
                drivingInfo.toString()
            )
        }

        override fun onNavigationStatus(status: NavigationStatus) {                     // 내비 상태 (안내 중 등)
            logGap("status", "$status")
            Log.d("PLEOS", "내비 상태 = $status"); sendSignal("navi_status", status.toString())
        }

        override fun onRouteStarted(routeStartInfo: RouteStartInfo) {                   // 경로 안내 시작
            Log.d("PLEOS", "경로 시작 = $routeStartInfo"); sendSignal(
                "navi_route_start",
                routeStartInfo.toString()
            )
        }

        override fun onDestinationArrived(destinationArrivedInfo: DestinationArrivedInfo) {  // 목적지 도착
            Log.d("PLEOS", "도착 = $destinationArrivedInfo"); sendSignal(
                "navi_arrived",
                destinationArrivedInfo.toString()
            )
        }

        override fun onError(errorCode: NaviErrorCode) {                                // 오류
            Log.e("PLEOS", "내비 오류 = $errorCode"); sendSignal("navi_error", errorCode.toString())
        }
    }


    // 차속 실시간 콜백 (AAOS 표준 API)
    private val speedCallback = object : CarPropertyManager.CarPropertyEventCallback {
        override fun onChangeEvent(value: CarPropertyValue<*>) {
            val kmh = ((value.value as Float) * 3.6f).toInt()            // m/s → km/h
            if (kmh != lastSentSpeed) {                                   // 1km/h 이상 바뀔 때만 전송
                lastSentSpeed = kmh
                Log.d("PLEOS", "차속 = $kmh km/h")
                sendSignal("speed_kmh", kmh.toString())
            }
        }

        override fun onErrorEvent(propId: Int, zone: Int) {
            Log.e("PLEOS", "차속 수신 오류 propId=$propId")
        }
    }

    // 비상등·주차브레이크·시동 실시간 콜백 (AAOS 표준 API)
    private val aaosCallback = object : CarPropertyManager.CarPropertyEventCallback {
        override fun onChangeEvent(value: CarPropertyValue<*>) {
            when (value.propertyId) {
                VehiclePropertyIds.HAZARD_LIGHTS_STATE ->                     // 비상등: 0 꺼짐 / 1 켜짐
                {
                    Log.d("PLEOS", "비상등 = ${value.value}"); sendSignal(
                    "hazard",
                    value.value.toString()
                )
                }

                VehiclePropertyIds.PARKING_BRAKE_ON ->                        // 주차브레이크: true 채움 / false 해제
                {
                    Log.d("PLEOS", "주차브레이크 = ${value.value}"); sendSignal(
                    "parking_brake",
                    value.value.toString()
                )
                }

                VehiclePropertyIds.IGNITION_STATE ->                          // 시동: 1 LOCK / 2 OFF / 3 ACC / 4 ON / 5 START
                {
                    Log.d("PLEOS", "시동 = ${value.value}"); sendSignal(
                    "ignition",
                    value.value.toString()
                )
                }
            }
        }

        override fun onErrorEvent(propId: Int, zone: Int) {
            Log.e(
                "PLEOS",
                "AAOS 수신 오류 ${VehiclePropertyIds.toString(propId)}"
            )   // 어떤 속성이 실패했는지 이름으로 출력
        }
    }


    // 위치 실시간 리스너 (안드로이드 표준 GPS)
    private val locationListener = LocationListener { loc: Location ->
        val kmh =
            (loc.speed * 3.6f).toInt()                                      // GPS 속도 m/s → km/h
        Log.d(
            "PLEOS",
            "위치 = ${loc.latitude}, ${loc.longitude} / 방향 ${loc.bearing}° / 정확도 ${loc.accuracy}m"
        )  // 로그 확인용
        sendSignal("location", "${loc.latitude},${loc.longitude}")               // 위도,경도 순서
        sendSignal("gps_speed_kmh", kmh.toString())                              // GPS 기준 속도
        sendSignal(
            "heading",
            if (loc.hasBearing()) loc.bearing.toString() else "none"
        )       // 진행 방향 0~360° (북=0, 동=90), 정지 시 없음
        sendSignal(
            "gps_accuracy",
            if (loc.hasAccuracy()) loc.accuracy.toString() else "none"
        ) // 오차 반경(m), 작을수록 정확
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        vehicle = Vehicle(this)
        vehicle.initialize()                              // 차량 서비스 연결

        // 문 6개: 1회 조회 + 실시간 감지
        doorAreas.forEach { (name, value) ->
            vehicle.getDoor().getCurrentDoorPosition(
                area = DoorArea(value),
                onComplete = { pos: Int? ->
                    Log.d("PLEOS", "$name = $pos"); sendSignal(
                    name,
                    pos.toString()
                )
                },  // 현재 상태
                onFailed = { e: Exception -> Log.e("PLEOS", "$name 조회 실패", e) }
            )
            vehicle.getDoor()
                .registerDoorPosition(DoorArea(value), doorListeners.getValue(name))  // 실시간 감지 시작
        }

        // 방향지시등 1회 조회 + 실시간 감지
        vehicle.getTurnSignal().getCurrentTurnSignalState(
            onComplete = { state ->
                Log.d("PLEOS", "방향지시등 = $state")
                sendSignal("turn_signal", state.toString())
            },
            onFailed = { e -> Log.e("PLEOS", "방향지시등 실패", e) }
        )
        vehicle.getTurnSignal().registerTurnSignalState(turnSignalListener)

        // 기어 1회 조회 + 실시간 감지 (Pleos)
        vehicle.getGear().getCurrentGearSelectionState(
            onComplete = { gear ->
                Log.d("PLEOS", "기어 = $gear")
                sendSignal("gear", gear.toString())                      // GEAR_PARK / GEAR_DRIVE 등
            },
            onFailed = { e -> Log.e("PLEOS", "기어 조회 실패", e) }
        )
        vehicle.getGear().registerGearSelection(gearListener)            // ★ 추가: 기어 실시간 감지 시작

        // 텔테일 1회 조회 + 실시간 감지
        vehicle.getSafety().getTelltalesInfo(
            onComplete = { t ->
                Log.d("PLEOS", "텔테일 = $t"); sendSignal(
                "telltales",
                t.toString()
            )
            },  // 현재 상태
            onFailed = { e -> Log.e("PLEOS", "텔테일 조회 실패", e) }
        )
        vehicle.getSafety().registerTelltales(telltaleListener)            // 실시간 감지 시작
        naviHelper = NaviHelper(applicationContext)
        naviHelper.initialize(
            onConnected = {
                Log.d(
                    "PLEOS",
                    "내비 연결 성공"
                ); naviHelper.addListener(naviListener); handler.post(naviPoll)
            },   // 연결 후 등록
            onFailed = { t ->
                Log.e(
                    "PLEOS",
                    "내비 연결 실패",
                    t
                )
            }                                     // 재시도 모두 실패
        )


        // 차속·위치 권한 확인 → 있으면 시작, 없으면 허용 팝업
        val needed = (arrayOf(
            "android.car.permission.CAR_SPEED",                 // 차속
            android.Manifest.permission.ACCESS_FINE_LOCATION,   // 위치
            // ★ 11/10 제외: CAR_EXTERIOR_LIGHTS(비상등)는 시스템 앱 전용이라 절대 허용 안 됨
            //   → 목록에 있으면 실행할 때마다 권한창이 떠서 앱 화면을 가림
            "android.car.permission.CAR_POWERTRAIN"             // 주차브레이크·시동
        ) + (if (android.os.Build.VERSION.SDK_INT >= 33)
                arrayOf(android.Manifest.permission.POST_NOTIFICATIONS)   // ★ 11/10 추가: 안내 서비스 상단 알림
             else emptyArray()))
            .filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (needed.isEmpty()) startAll() else requestPermissions(needed.toTypedArray(), 100)

        // ★ 11/10 추가: 안내 음성 서비스 시작 (기존 TTS 앱 기능, 다른 앱이 앞에 있어도 계속 동작)
        ContextCompat.startForegroundService(this, Intent(this, GuidanceService::class.java))

        enableEdgeToEdge()
        setContent {
            CoDriverTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    GuidanceScreen(modifier = Modifier.padding(innerPadding))   // ★ 11/10 변경: 마지막 안내 표시
                }
            }
        }
    }

    // 차속 감지 시작 (AAOS)
    private fun startSpeed() {
        try {
            car = Car.createCar(this)
            val pm = car?.getCarManager(Car.PROPERTY_SERVICE) as CarPropertyManager
            pm.registerCallback(
                speedCallback, VehiclePropertyIds.PERF_VEHICLE_SPEED,
                CarPropertyManager.SENSOR_RATE_NORMAL
            )
            Log.d("PLEOS", "차속 감지 시작")
        } catch (e: Exception) {
            Log.e("PLEOS", "차속 감지 실패", e)                          // SecurityException = OS 차단
        }
    }

    // 위치 감지 시작 (GPS, 1초 또는 1m마다)
    private fun startLocation() {
        try {
            val lm = getSystemService(LOCATION_SERVICE) as LocationManager
            lm.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000L, 1f, locationListener)
            Log.d("PLEOS", "위치 감지 시작")
        } catch (e: SecurityException) {
            Log.e("PLEOS", "위치 권한 없음", e)
        }
    }

    // 모든 감지 시작 (각각 실패해도 나머지는 계속)
    private fun startAll() {
        startSpeed()                                                             // 차속
        startLocation()                                                          // 위치
        startAaosExtra()                                                         // 비상등·주차브레이크·시동
    }

    // AAOS 추가 신호 감지 시작
    private fun startAaosExtra() {
        Log.d(
            "PLEOS",
            "외부등 권한 = ${checkSelfPermission("android.car.permission.CAR_EXTERIOR_LIGHTS") == PackageManager.PERMISSION_GRANTED}"
        )
        val c = car ?: Car.createCar(this).also { car = it }                     // 차속에서 만든 Car 재사용
        val pm = c.getCarManager(Car.PROPERTY_SERVICE) as CarPropertyManager
        listOf(
            VehiclePropertyIds.HAZARD_LIGHTS_STATE,                              // 비상등
            VehiclePropertyIds.PARKING_BRAKE_ON,                                 // 주차브레이크
            VehiclePropertyIds.IGNITION_STATE                                    // 시동
        ).forEach { id ->
            try {
                Log.d(
                    "PLEOS",
                    "${VehiclePropertyIds.toString(id)} 지원 = ${pm.getCarPropertyConfig(id) != null}"
                )
                val ok = pm.registerCallback(
                    aaosCallback,
                    id,
                    CarPropertyManager.SENSOR_RATE_ONCHANGE
                )  // 값이 바뀔 때만 수신
                Log.d(
                    "PLEOS",
                    "AAOS 감지 시작 ${VehiclePropertyIds.toString(id)} = $ok"
                )              // true면 성공
            } catch (e: Exception) {
                Log.e(
                    "PLEOS",
                    "AAOS 감지 실패 ${VehiclePropertyIds.toString(id)}",
                    e
                )                 // 권한·미지원 원인 출력
            }
        }
    }

    // 권한 팝업 결과 처리 → 허용 여부와 상관없이 시도 (거부된 것은 각 함수에서 로그만 남김)
    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 100) startAll()
    }


    // 신호를 Python 서버로 보내는 함수 (별도 스레드)
    private fun sendSignal(type: String, value: String) {
        Thread {
            try {
                val url = java.net.URL("http://10.0.2.2:8000/signal")
                val conn = url.openConnection() as java.net.HttpURLConnection
                conn.connectTimeout = 3000
                conn.readTimeout = 3000
                conn.requestMethod = "POST"
                conn.setRequestProperty("Content-Type", "application/json")
                conn.doOutput = true
                val body = org.json.JSONObject()
                    .put("type", type)
                    .put("value", value)
                    .put("ts", System.currentTimeMillis())
                    .toString()
                conn.outputStream.use { it.write(body.toByteArray()) }
                val res = conn.inputStream.bufferedReader().readText()
                Log.d("PLEOS_NET", "서버 응답: $res")
                conn.disconnect()
            } catch (e: Exception) {
                Log.e("PLEOS_NET", "전송 실패", e)
            }
        }.start()
    }

    override fun onDestroy() {
        handler.removeCallbacks(naviPoll)
        doorAreas.forEach { (name, value) ->
            vehicle.getDoor()
                .unregisterDoorPosition(DoorArea(value), doorListeners.getValue(name))  // 문 감지 해제
        }
        vehicle.getTurnSignal()
            .unregisterTurnSignalState(turnSignalListener)              // 방향지시등 감지 종료
        vehicle.getGear().unregisterGearSelection(gearListener) // ★ 추가: 기어 감지 종료
        vehicle.getSafety().unregisterTelltales(telltaleListener)
        (car?.getCarManager(Car.PROPERTY_SERVICE) as? CarPropertyManager)?.unregisterCallback(
            speedCallback
        )  // 차속 감지 종료
        (car?.getCarManager(Car.PROPERTY_SERVICE) as? CarPropertyManager)?.unregisterCallback(
            aaosCallback
        )   // ← 추가: AAOS 추가 신호 해제
        car?.disconnect()                                                                  // Car 서비스 해제
        (getSystemService(LOCATION_SERVICE) as LocationManager).removeUpdates(locationListener)  // 위치 감지 종료
        if (::naviHelper.isInitialized) {                 // 초기화된 경우만
            naviHelper.removeListener(naviListener)       // 내비 리스너 해제
            naviHelper.release()                          // 내비 SDK 해제
        }
        vehicle.release()                                                                  // Pleos SDK 해제
        stopService(Intent(this, GuidanceService::class.java))                             // ★ 11/10 추가: 안내 서비스 종료
        super.onDestroy()
    }
}

// ★ 11/10 추가: 앱 화면 = 마지막 음성 안내 문장 (서비스가 받을 때마다 자동 갱신)
@Composable
fun GuidanceScreen(modifier: Modifier = Modifier) {
    val k = 4f                                                               // ★ 글자 배율 (원래 크기의 4배) → 이 숫자만 바꾸면 전체 조절
    Box(
        modifier = modifier.fillMaxSize().padding(32.dp),                    // 화면 전체 차지
        contentAlignment = Alignment.Center                                  // ★ 안쪽 내용을 상하·좌우 가운데로
    ) {
        Column(
            modifier = Modifier.verticalScroll(rememberScrollState()),       // 안내가 길어 화면을 넘으면 스크롤
            horizontalAlignment = Alignment.CenterHorizontally               // ★ 줄마다 좌우 가운데
        ) {
            Text("SoloM",
                fontSize = (28 * k).sp, fontWeight = FontWeight.Bold,
                textAlign = TextAlign.Center)                                // 앱 제목 (28 → 112sp)
            Text("최근 안내",
                fontSize = (14 * k).sp, color = Color.Gray,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 32.dp))                    // 작은 제목 (14 → 56sp)
            Text(GuidanceService.lastText.value,
                fontSize = (24 * k).sp, lineHeight = (32 * k).sp,
                fontWeight = FontWeight.SemiBold,
                textAlign = TextAlign.Center,                                // ★ 여러 줄로 넘어가도 가운데 정렬
                modifier = Modifier.padding(top = 16.dp))                    // 안내 문구 (24 → 96sp)
        }
    }
}

@Composable
fun Greeting(name: String, modifier: Modifier = Modifier) {
    Text(text = "Hello $name!", modifier = modifier)
}

@Preview(showBackground = true)
@Composable
fun GreetingPreview() {
    CoDriverTheme { Greeting("Android") }
}

// enum 값 목록을 로그로 출력하는 도우미 함수 (필요할 때 다시 사용)
fun <T : Enum<T>> dumpEnum(name: String, values: Array<T>) {
    values.forEach { v ->
        val fields = v.javaClass.declaredFields
            .filter { !java.lang.reflect.Modifier.isStatic(it.modifiers) }
            .joinToString { f -> f.isAccessible = true; "${f.name}=${f.get(v)}" }
        Log.d("PLEOS_ENUM", "$name.${v.name} ($fields)")
    }
}