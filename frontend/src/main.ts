import { createApp } from "vue";
import { createPinia } from "pinia";
import {
  create,
  NButton,
  NCard,
  NCheckbox,
  NConfigProvider,
  NCollapse,
  NCollapseItem,
  NDataTable,
  NDialogProvider,
  NDrawer,
  NDrawerContent,
  NDropdown,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NMenu,
  NMessageProvider,
  NModal,
  NNotificationProvider,
  NRadioButton,
  NRadioGroup,
  NSelect,
  NSpace,
  NSwitch,
  NTabPane,
  NTabs,
  NTag,
  NThing,
} from "naive-ui";
import App from "./App.vue";
import router from "./router";

const app = createApp(App);
const naive = create({
  components: [
    NButton,
    NCard,
    NCheckbox,
    NConfigProvider,
    NCollapse,
    NCollapseItem,
    NDataTable,
    NDialogProvider,
    NDrawer,
    NDrawerContent,
    NDropdown,
    NForm,
    NFormItem,
    NInput,
    NInputNumber,
    NMenu,
    NMessageProvider,
    NModal,
    NNotificationProvider,
    NRadioButton,
    NRadioGroup,
    NSelect,
    NSpace,
    NSwitch,
    NTabPane,
    NTabs,
    NTag,
    NThing,
  ],
});
app.use(createPinia());
app.use(router);
app.use(naive);
app.mount("#app");
