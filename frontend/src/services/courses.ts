import { request } from './api';

export type CourseMode = 'ONLINE' | 'CLASSROOM' | 'BOTH';
export type Seats = 'OPEN' | 'FULL';

export interface CourseBatch {
  id: string;
  start_date: string; // YYYY-MM-DD
  timings: string;
  mode: CourseMode | null; // null = the course's mode
  medium: string | null;
  seats: Seats;
  /** UPCOMING = offered to callers; FULL = shown as full; STARTED = past its start date, no longer offered */
  state: 'UPCOMING' | 'FULL' | 'STARTED';
}

export interface Course {
  id: string;
  name: string;
  aliases: string | null;
  category: string | null;
  audience: string | null;
  eligibility: string | null;
  duration: string;
  mode: CourseMode;
  medium: string | null;
  fee: string;
  instalments: string | null;
  highlights: string | null;
  certificate: boolean | null;
  extra_details: string | null;
  status: 'ACTIVE' | 'HIDDEN';
  sort_order: number;
  updated_at: string | null;
  batches: CourseBatch[];
}

export interface CourseChange {
  id: string;
  course_id: string | null;
  course_name: string;
  action: string;
  summary: string;
  fee_changed: boolean;
  actor: 'CLIENT' | 'TEAM';
  actor_name: string | null;
  created_at: string | null;
}

export type CourseInput = Partial<Omit<Course, 'id' | 'batches' | 'updated_at'>>;
export type BatchInput = Partial<Omit<CourseBatch, 'id' | 'state'>>;

/** The catalogue API, the same for the client portal and the admin client page (only the base path differs). */
export interface CoursesApi {
  list: () => Promise<{ today: string; courses: Course[] }>;
  changes: () => Promise<CourseChange[]>;
  create: (body: CourseInput) => Promise<Course>;
  update: (courseId: string, body: CourseInput) => Promise<Course>;
  addBatch: (courseId: string, body: BatchInput) => Promise<Course>;
  updateBatch: (courseId: string, batchId: string, body: BatchInput) => Promise<Course>;
  deleteBatch: (courseId: string, batchId: string) => Promise<Course>;
}

const coursesApi = (base: string): CoursesApi => ({
  list: () => request(base),
  changes: () => request(`${base}/changes`),
  create: (body) => request(base, { method: 'POST', body: JSON.stringify(body) }),
  update: (courseId, body) => request(`${base}/${courseId}`, { method: 'PATCH', body: JSON.stringify(body) }),
  addBatch: (courseId, body) => request(`${base}/${courseId}/batches`, { method: 'POST', body: JSON.stringify(body) }),
  updateBatch: (courseId, batchId, body) =>
    request(`${base}/${courseId}/batches/${batchId}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteBatch: (courseId, batchId) => request(`${base}/${courseId}/batches/${batchId}`, { method: 'DELETE' }),
});

export const portalCoursesService = coursesApi('/portal/courses');
export const clientCoursesService = (clientId: string) => coursesApi(`/clients/${clientId}/courses`);
