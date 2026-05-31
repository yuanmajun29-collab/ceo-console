<script setup lang="ts">
import { darkTheme, type GlobalThemeOverrides } from "naive-ui";
import { computed } from "vue";

const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: "#0b67f0",
    primaryColorHover: "#1d77ff",
    primaryColorPressed: "#0552c7",
    borderRadius: "8px",
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
  },
};

const theme = computed(() => null);
void darkTheme;
</script>

<template>
  <n-config-provider :theme="theme" :theme-overrides="themeOverrides">
    <n-message-provider>
      <n-notification-provider>
        <n-dialog-provider>
          <router-view />
        </n-dialog-provider>
      </n-notification-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<style>
html,
body,
#app {
  margin: 0;
  height: 100%;
  background: #f4f7fb;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Microsoft YaHei", sans-serif;
  color: #101827;
}
</style>
