import { createRouter, createWebHistory } from 'vue-router'
import HomeView from './views/HomeView.vue'
import AceStepPage from './views/ace-step/AceStepPage.vue'
import LoraTrainingPage from './views/ace-step/LoraTrainingPage.vue'
import Yue2Page from './views/yue2/Yue2Page.vue'
import StableAudioPage from './views/stable-audio/StableAudioPage.vue'
import ProjectsListPage from './views/editor/ProjectsListPage.vue'
import EditorPage from './views/editor/EditorPage.vue'
import ModelsPage from './views/models/ModelsPage.vue'
import IdeaPage from './views/idea/IdeaPage.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/ace-step', name: 'ace-step', component: AceStepPage },
    { path: '/ace-step/lora', name: 'ace-step-lora', component: LoraTrainingPage },
    { path: '/yue2', name: 'yue2', component: Yue2Page },
    { path: '/stable-audio', name: 'stable-audio', component: StableAudioPage },
    { path: '/editor', name: 'editor-projects', component: ProjectsListPage },
    // Weights and settings of every engine: a settings page, reached from the gear in the header.
    { path: '/models', name: 'models', component: ModelsPage },
    // One field for the idea; the prompt is written for the engine (RFC 0002).
    { path: '/idea', name: 'idea', component: IdeaPage },
    // A workspace: full width and one screen high on a desktop, no footer (see App.vue).
    { path: '/editor/:id', name: 'editor', component: EditorPage, props: true, meta: { workspace: true } },
  ],
})

export default router
