import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token') || localStorage.getItem('access_token')
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export interface TopicCard {
  topic_key: string
  space_type: string
  space_id?: string | null
  version: number
  status: string
  skill_goal: string
  summary: string
  chapter_count: number
  approved_entity_count: number
  updated_at?: string | null
}

export interface ChapterGlossaryItem {
  entity_id: string
  canonical_name: string
  entity_type: string
  short_definition: string
  detailed_explanation: string
  link_role: 'core' | 'glossary' | 'support'
}

export interface SkillChapter {
  chapter_id: string
  stage_id: string
  chapter_order: number
  title: string
  objective: string
  can_do_after: string
  practice_task: string
  pass_criteria: string
  estimated_minutes: number
  learning_points: string[]
  target_entity_ids: string[]
  glossary_entity_ids: string[]
  glossary: ChapterGlossaryItem[]
}

export interface SkillStage {
  stage_id: string
  stage_order: number
  title: string
  objective: string
  can_do_after: string
  chapters: SkillChapter[]
}

export interface SkillBlueprint {
  blueprint_id: string
  topic_key: string
  space_type: string
  space_id?: string | null
  version: number
  status: string
  skill_goal: string
  target_role: string
  summary: string
  source_fingerprint: string
  source_entity_count: number
  stages: SkillStage[]
}

export interface ChapterContent {
  chapter_id: string
  title: string
  objective: string
  can_do_after: string
  practice_task: string
  pass_criteria: string
  learning_points: string[]
  sections: Array<{ title: string; body: string }>
  glossary: ChapterGlossaryItem[]
}

export const skillBlueprintApi = {
  async listTopics(spaceType?: string) {
    const { data } = await api.get<TopicCard[]>('/tutorials/topics', {
      params: { space_type: spaceType || undefined },
    })
    return data
  },

  async getTopic(topicKey: string, params?: { spaceType?: string; spaceId?: string; force?: boolean }) {
    const { data } = await api.get<SkillBlueprint>(`/tutorials/topic/${encodeURIComponent(topicKey)}`, {
      params: {
        space_type: params?.spaceType || 'personal',
        space_id: params?.spaceId,
        force: params?.force || false,
      },
    })
    return data
  },

  async regenerateTopic(topicKey: string, payload?: { space_type?: string; space_id?: string }) {
    const { data } = await api.post<SkillBlueprint>(
      `/tutorials/topic/${encodeURIComponent(topicKey)}/regenerate`,
      payload || {},
    )
    return data
  },

  async getChapterContent(chapterId: string) {
    const response = await api.get(`/tutorials/chapter/${encodeURIComponent(chapterId)}/content`)
    return await response.data
  },

  async getLearningPath(topicKey: string, params?: { spaceType?: string; spaceId?: string; limit?: number }) {
    const { data } = await api.get(`/tutorials/path/${encodeURIComponent(topicKey)}`, {
      params: {
        space_type: params?.spaceType || 'personal',
        space_id: params?.spaceId,
        limit: params?.limit || 12,
      },
    })
    return data
  },
}
