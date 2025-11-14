package com.jones.aptracker.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jones.aptracker.BuildConfig
import com.jones.aptracker.network.RetrofitClient
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed class AppVersionState {
    object Checking : AppVersionState()
    object UpToDate : AppVersionState()
    data class Outdated(val storeUrl: String) : AppVersionState()
    data class Error(val message: String) : AppVersionState()
}

class MainViewModel(application: Application) : AndroidViewModel(application) {

    private val _versionState = MutableStateFlow<AppVersionState>(AppVersionState.Checking)
    val versionState = _versionState.asStateFlow()

    private val apiService = RetrofitClient.instance

    init {
        checkAppVersion()
    }

    fun checkAppVersion() {
        _versionState.value = AppVersionState.Checking
        viewModelScope.launch {
            try {
                val config = apiService.getConfig()
                val minVersion = config.min_app_version

                val currentVersion = BuildConfig.VERSION_CODE

                if (currentVersion >= minVersion) {
                    _versionState.value = AppVersionState.UpToDate
                } else {
                    _versionState.value = AppVersionState.Outdated("https://github.com/wrjones104/ap-tracker/releases")
                }

            } catch (e: Exception) {
                _versionState.value = AppVersionState.UpToDate
            }
        }
    }
}