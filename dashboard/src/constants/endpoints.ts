export interface ApiEndpoint {
  method: string;
  path: string;
  label: string;
  bodyHint: string;
}

export const API_ENDPOINTS: ApiEndpoint[] = [
  { method: 'POST', path: '/courses/', label: 'Create Course', bodyHint: '{\n  "title": "My Course",\n  "description": ""\n}' },
  { method: 'POST', path: '/courses/list/', label: 'List Courses', bodyHint: '' },
  { method: 'POST', path: '/courses/detail/', label: 'Course Detail', bodyHint: '{\n  "id": 1\n}' },
  { method: 'POST', path: '/courses/status/', label: 'Course Status', bodyHint: '{\n  "id": 1\n}' },
  { method: 'POST', path: '/courses/videos/', label: 'Course Videos', bodyHint: '{\n  "id": 1\n}' },
  { method: 'POST', path: '/courses/delete/', label: 'Delete Course', bodyHint: '{\n  "id": 1\n}' },
  { method: 'POST', path: '/videos/', label: 'Add Video To Course', bodyHint: '{\n  "course_id": 1,\n  "video_url": "https://vimeo.com/..."\n}' },
  { method: 'POST', path: '/videos/bulk/', label: 'Bulk Add Videos', bodyHint: '{\n  "course_id": 1,\n  "video_urls": [\n    "https://vimeo.com/...",\n    "https://vimeo.com/..."\n  ]\n}' },
  { method: 'POST', path: '/videos/status/', label: 'Video Status', bodyHint: '{\n  "id": 1\n}' },
  { method: 'POST', path: '/videos/delete/', label: 'Delete Video', bodyHint: '{\n  "course_id": 1,\n  "id": 1\n}' },
  { method: 'POST', path: '/query/video/', label: 'Query Video', bodyHint: '{\n  "video_id": 1,\n  "question": "What is this about?"\n}' },
  { method: 'POST', path: '/query/course/', label: 'Query Course', bodyHint: '{\n  "course_id": 1,\n  "question": "Summarize all topics",\n  "include_study_materials": true\n}' },
  { method: 'POST', path: '/study-materials/upload/', label: 'Upload Study Material', bodyHint: 'multipart/form-data: name, description, zip_file' },
  { method: 'GET',  path: '/study-materials/', label: 'List Study Materials', bodyHint: '' },
  { method: 'GET',  path: '/study-materials/1/status/', label: 'SM Status', bodyHint: '' },
  { method: 'POST', path: '/study-materials/1/query/', label: 'Query SM', bodyHint: '{\n  "question": "What is this about?"\n}' },
  { method: 'POST', path: '/study-materials/files/1/query/', label: 'Query File', bodyHint: '{\n  "question": "What is this file about?"\n}' },
  { method: 'POST', path: '/study-materials/1/retry/', label: 'Retry SM Processing', bodyHint: '' },
  { method: 'DELETE', path: '/study-materials/1/delete/', label: 'Delete SM', bodyHint: '' },
  { method: 'POST', path: '/study-materials/1/merge-to-course/1/', label: 'Merge SM to Course', bodyHint: '' },
];

export const COMMON_HEADERS: string[] = [
  'Accept', 'Accept-Charset', 'Accept-Encoding', 'Accept-Language',
  'Access-Control-Request-Headers', 'Access-Control-Request-Method',
  'Authorization', 'Cache-Control', 'Connection', 'Content-Length',
  'Content-MD5', 'Content-Transfer-Encoding', 'Content-Type',
  'Cookie', 'Date', 'Expect', 'Forwarded', 'From',
  'Host', 'If-Match', 'If-Modified-Since', 'If-None-Match',
  'If-Range', 'If-Unmodified-Since', 'Keep-Alive', 'Max-Forwards',
  'Origin', 'Pragma', 'Proxy-Authorization', 'Range', 'Referer',
  'TE', 'Trailer', 'Transfer-Encoding', 'Upgrade', 'User-Agent',
  'Via', 'Warning', 'X-API-Key', 'X-Auth-Token', 'X-Forwarded-For',
  'X-Forwarded-Host', 'X-Forwarded-Proto', 'X-Requested-With',
];
