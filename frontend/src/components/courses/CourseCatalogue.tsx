import React, { useEffect, useState } from 'react';
import { CalendarPlus, Eye, EyeOff, GraduationCap, History, Pencil, Plus, Trash2, X } from 'lucide-react';
import { Button } from '../common/Button';
import { Badge } from '../common/Badge';
import { BatchInput, Course, CourseBatch, CourseChange, CourseInput, CourseMode, CoursesApi } from '../../services/courses';

const MODES: Array<{ value: CourseMode; label: string }> = [
  { value: 'ONLINE', label: 'Online' },
  { value: 'CLASSROOM', label: 'Classroom' },
  { value: 'BOTH', label: 'Online and classroom' },
];
const modeLabel = (m: string | null) => MODES.find((x) => x.value === m)?.label || '';
const showDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });

const input =
  'w-full rounded border border-[#153945] bg-[#071419] px-2.5 py-2 text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:outline-none';

interface CourseDraft {
  id: string | null;
  values: CourseInput;
}
interface BatchDraft {
  courseId: string;
  id: string | null;
  values: BatchInput;
}

const EMPTY_COURSE: CourseInput = { name: '', duration: '', mode: 'BOTH', fee: '' };
const EMPTY_BATCH: BatchInput = { start_date: '', timings: '', mode: null, medium: null, seats: 'OPEN' };

const Field: React.FC<{ label: string; hint?: string; required?: boolean; wide?: boolean; children: React.ReactNode }> = ({
  label, hint, required, wide, children,
}) => (
  <label className={`block space-y-1 ${wide ? 'sm:col-span-2' : ''}`}>
    <span className="text-[11px] font-medium text-slate-300">
      {label} {required && <span className="text-[#00df8f]">*</span>}
    </span>
    {children}
    {hint && <span className="block text-[11px] text-slate-500">{hint}</span>}
  </label>
);

/**
 * A coaching centre's courses and batches. AI employees quote fees and batch dates only from here: batches stop
 * being offered once their start date passes, and full ones are never offered. Used in the client portal and on
 * the admin client page (which also shows the change history).
 */
export const CourseCatalogue: React.FC<{ api: CoursesApi; showChanges?: boolean }> = ({ api, showChanges = false }) => {
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [today, setToday] = useState('');
  const [changes, setChanges] = useState<CourseChange[]>([]);
  const [courseDraft, setCourseDraft] = useState<CourseDraft | null>(null);
  const [batchDraft, setBatchDraft] = useState<BatchDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const data = await api.list();
      setCourses(data.courses);
      setToday(data.today);
      if (showChanges) setChanges(await api.changes());
    } catch (err: any) {
      setError(err.message || 'Could not load courses.');
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
      return true;
    } catch (err: any) {
      setError(err.message || 'Something went wrong.');
      return false;
    } finally {
      setBusy(false);
    }
  };

  const saveCourse = async () => {
    if (!courseDraft) return;
    const v = courseDraft.values;
    if (!v.name?.trim() || !v.duration?.trim() || !v.fee?.trim()) return setError('Add the course name, duration and fee.');
    const ok = await run(() => (courseDraft.id ? api.update(courseDraft.id, v) : api.create(v)));
    if (ok) setCourseDraft(null);
  };

  const saveBatch = async () => {
    if (!batchDraft) return;
    const v = batchDraft.values;
    if (!v.start_date || !v.timings?.trim()) return setError('Add the start date and timings.');
    const ok = await run(() =>
      batchDraft.id ? api.updateBatch(batchDraft.courseId, batchDraft.id, v) : api.addBatch(batchDraft.courseId, v)
    );
    if (ok) setBatchDraft(null);
  };

  const setCourse = (patch: CourseInput) => courseDraft && setCourseDraft({ ...courseDraft, values: { ...courseDraft.values, ...patch } });
  const setBatch = (patch: BatchInput) => batchDraft && setBatchDraft({ ...batchDraft, values: { ...batchDraft.values, ...patch } });

  const courseForm = courseDraft && (
    <div className="space-y-3 rounded-lg border border-[#1b3a46] bg-[#06141a] p-3">
      <p className="text-xs font-semibold text-slate-200">{courseDraft.id ? 'Edit course' : 'New course'}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Course name" required>
          <input className={input} placeholder="e.g. Python Full Stack" value={courseDraft.values.name || ''}
            onChange={(e) => setCourse({ name: e.target.value })} />
        </Field>
        <Field label="Other names students use" hint="Helps the assistant recognise the course on calls">
          <input className={input} placeholder="e.g. Python, full stack" value={courseDraft.values.aliases || ''}
            onChange={(e) => setCourse({ aliases: e.target.value })} />
        </Field>
        <Field label="Total fee" required hint="Exactly as you quote it">
          <input className={input} placeholder="e.g. ₹25,000" value={courseDraft.values.fee || ''}
            onChange={(e) => setCourse({ fee: e.target.value })} />
        </Field>
        <Field label="Instalments">
          <input className={input} placeholder="e.g. 2 instalments of ₹12,500" value={courseDraft.values.instalments || ''}
            onChange={(e) => setCourse({ instalments: e.target.value })} />
        </Field>
        <Field label="Duration" required>
          <input className={input} placeholder="e.g. 8 weeks, 4 months" value={courseDraft.values.duration || ''}
            onChange={(e) => setCourse({ duration: e.target.value })} />
        </Field>
        <Field label="Mode" required>
          <select className={input} value={courseDraft.values.mode || 'BOTH'}
            onChange={(e) => setCourse({ mode: e.target.value as CourseMode })}>
            {MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </Field>
        <Field label="Medium of teaching">
          <input className={input} placeholder="e.g. Telugu, English" value={courseDraft.values.medium || ''}
            onChange={(e) => setCourse({ medium: e.target.value })} />
        </Field>
        <Field label="Category">
          <input className={input} placeholder="e.g. Competitive exam, IT / software" value={courseDraft.values.category || ''}
            onChange={(e) => setCourse({ category: e.target.value })} />
        </Field>
        <Field label="Who is it for?">
          <input className={input} placeholder="e.g. Freshers, working professionals" value={courseDraft.values.audience || ''}
            onChange={(e) => setCourse({ audience: e.target.value })} />
        </Field>
        <Field label="Eligibility">
          <input className={input} placeholder="e.g. Any graduate" value={courseDraft.values.eligibility || ''}
            onChange={(e) => setCourse({ eligibility: e.target.value })} />
        </Field>
        <Field label="What is covered" wide>
          <textarea rows={3} className={input} placeholder="Main topics, projects, study material, test series"
            value={courseDraft.values.highlights || ''} onChange={(e) => setCourse({ highlights: e.target.value })} />
        </Field>
        <Field label="Extra details" wide hint="Exams: exam name, test series. IT: tools, projects, placement assistance.">
          <textarea rows={2} className={input} value={courseDraft.values.extra_details || ''}
            onChange={(e) => setCourse({ extra_details: e.target.value })} />
        </Field>
        <Field label="Certificate on completion">
          <select className={input}
            value={courseDraft.values.certificate == null ? '' : courseDraft.values.certificate ? 'yes' : 'no'}
            onChange={(e) => setCourse({ certificate: e.target.value === '' ? null : e.target.value === 'yes' })}>
            <option value="">Not specified</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </Field>
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={() => setCourseDraft(null)}>
          <X className="mr-1 h-3.5 w-3.5" /> Cancel
        </Button>
        <Button variant="primary" size="sm" isLoading={busy} onClick={saveCourse}>
          {courseDraft.id ? 'Save changes' : 'Add course'}
        </Button>
      </div>
    </div>
  );

  const batchForm = (course: Course) =>
    batchDraft?.courseId === course.id && (
      <div className="space-y-3 rounded-lg border border-[#1b3a46] bg-[#06141a] p-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Start date" required>
            <input type="date" className={input} min={today} value={batchDraft.values.start_date || ''}
              onChange={(e) => setBatch({ start_date: e.target.value })} />
          </Field>
          <Field label="Days and timings" required>
            <input className={input} placeholder="e.g. Weekdays 7–9 PM" value={batchDraft.values.timings || ''}
              onChange={(e) => setBatch({ timings: e.target.value })} />
          </Field>
          <Field label="Mode">
            <select className={input} value={batchDraft.values.mode || ''}
              onChange={(e) => setBatch({ mode: (e.target.value || null) as CourseMode | null })}>
              <option value="">Same as course ({modeLabel(course.mode)})</option>
              {MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </Field>
          <Field label="Medium">
            <input className={input} placeholder={course.medium ? `Same as course (${course.medium})` : 'e.g. Telugu'}
              value={batchDraft.values.medium || ''} onChange={(e) => setBatch({ medium: e.target.value || null })} />
          </Field>
          <Field label="Seats">
            <select className={input} value={batchDraft.values.seats || 'OPEN'}
              onChange={(e) => setBatch({ seats: e.target.value as 'OPEN' | 'FULL' })}>
              <option value="OPEN">Open</option>
              <option value="FULL">Full</option>
            </select>
          </Field>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => setBatchDraft(null)}>
            <X className="mr-1 h-3.5 w-3.5" /> Cancel
          </Button>
          <Button variant="primary" size="sm" isLoading={busy} onClick={saveBatch}>
            {batchDraft.id ? 'Save batch' : 'Add batch'}
          </Button>
        </div>
      </div>
    );

  const batchRow = (course: Course, b: CourseBatch) => (
    <li key={b.id} className={`flex flex-wrap items-center justify-between gap-2 px-3 py-2 ${b.state === 'STARTED' ? 'opacity-50' : ''}`}>
      <span className="min-w-0">
        <span className="font-semibold text-slate-200">{showDate(b.start_date)}</span>
        <span className="text-slate-400"> · {b.timings}</span>
        {(b.mode || b.medium) && (
          <span className="text-slate-500"> · {[modeLabel(b.mode), b.medium].filter(Boolean).join(', ')}</span>
        )}
      </span>
      <span className="flex items-center gap-1">
        {b.state === 'UPCOMING' && <Badge variant="green">Offered</Badge>}
        {b.state === 'FULL' && <Badge variant="yellow">Full</Badge>}
        {b.state === 'STARTED' && <Badge variant="gray">Started</Badge>}
        {b.state !== 'STARTED' && (
          <button type="button" disabled={busy}
            onClick={() => run(() => api.updateBatch(course.id, b.id, { seats: b.seats === 'FULL' ? 'OPEN' : 'FULL' }))}
            className="rounded px-2 py-1 text-[11px] text-slate-400 hover:bg-[#0c2129] hover:text-slate-100">
            {b.seats === 'FULL' ? 'Reopen' : 'Mark full'}
          </button>
        )}
        <button type="button" title="Edit batch"
          onClick={() => setBatchDraft({ courseId: course.id, id: b.id, values: { start_date: b.start_date, timings: b.timings, mode: b.mode, medium: b.medium, seats: b.seats } })}
          className="rounded p-1.5 text-slate-400 hover:bg-[#0c2129] hover:text-slate-100">
          <Pencil className="h-3.5 w-3.5" />
        </button>
        <button type="button" title="Remove batch"
          onClick={() => window.confirm(`Remove the ${showDate(b.start_date)} batch?`) && run(() => api.deleteBatch(course.id, b.id))}
          className="rounded p-1.5 text-slate-400 hover:bg-[#0c2129] hover:text-rose-300">
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </span>
    </li>
  );

  return (
    <div className="space-y-3 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-slate-400">
          Your AI assistant quotes fees and batch dates only from here. Batches stop being offered once their start date
          passes, and full batches are never offered. Changes apply from the next call.
        </p>
        <Button variant="primary" size="sm" disabled={busy}
          onClick={() => { setBatchDraft(null); setCourseDraft({ id: null, values: { ...EMPTY_COURSE } }); }}>
          <Plus className="mr-1.5 h-3.5 w-3.5" /> Add course
        </Button>
      </div>

      {error && <p className="rounded border border-rose-800/50 bg-rose-950/40 p-2 text-rose-300">{error}</p>}
      {courseDraft && !courseDraft.id && courseForm}

      {courses === null ? (
        <p className="text-slate-500">Loading courses...</p>
      ) : courses.length === 0 && !courseDraft ? (
        <p className="rounded-lg border border-dashed border-[#1b3a46] p-4 text-center text-slate-500">
          No courses yet. Add your first course with its fee, then add its upcoming batches.
        </p>
      ) : (
        <div className="space-y-3">
          {courses.map((course) =>
            courseDraft?.id === course.id ? (
              <div key={course.id}>{courseForm}</div>
            ) : (
              <div key={course.id} className={`rounded-lg border border-[#102d38] ${course.status === 'HIDDEN' ? 'opacity-60' : ''}`}>
                <div className="flex flex-wrap items-start justify-between gap-2 p-3">
                  <span className="flex min-w-0 gap-2.5">
                    <GraduationCap className="mt-0.5 h-4 w-4 shrink-0 text-[#00df8f]" />
                    <span className="min-w-0">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-slate-100">{course.name}</span>
                        {course.status === 'HIDDEN' && <Badge variant="gray">Hidden from callers</Badge>}
                      </span>
                      <span className="mt-0.5 block text-slate-400">
                        {course.fee}{course.instalments ? ` (${course.instalments})` : ''} · {course.duration} · {modeLabel(course.mode)}
                        {course.medium ? ` · ${course.medium}` : ''}
                      </span>
                      {course.aliases && <span className="mt-0.5 block text-[11px] text-slate-500">Also called: {course.aliases}</span>}
                    </span>
                  </span>
                  <span className="flex shrink-0 gap-1">
                    <button type="button" title="Edit course"
                      onClick={() => {
                        setBatchDraft(null);
                        const { id, batches, updated_at, ...values } = course;
                        void batches; void updated_at;
                        setCourseDraft({ id, values });
                      }}
                      className="rounded p-1.5 text-slate-400 hover:bg-[#0c2129] hover:text-slate-100">
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button type="button" disabled={busy}
                      title={course.status === 'HIDDEN' ? 'Offer to callers again' : 'Hide from callers'}
                      onClick={() => run(() => api.update(course.id, { status: course.status === 'HIDDEN' ? 'ACTIVE' : 'HIDDEN' }))}
                      className="rounded p-1.5 text-slate-400 hover:bg-[#0c2129] hover:text-slate-100">
                      {course.status === 'HIDDEN' ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
                    </button>
                  </span>
                </div>
                <div className="space-y-2 border-t border-[#102d38] p-3">
                  {course.batches.length > 0 ? (
                    <ul className="divide-y divide-[#102d38] rounded border border-[#102d38]">
                      {course.batches.map((b) => batchRow(course, b))}
                    </ul>
                  ) : (
                    <p className="text-slate-500">No upcoming batch. Callers will be told the next batch isn't announced yet.</p>
                  )}
                  {batchForm(course)}
                  {batchDraft?.courseId !== course.id && (
                    <button type="button"
                      onClick={() => { setCourseDraft(null); setBatchDraft({ courseId: course.id, id: null, values: { ...EMPTY_BATCH } }); }}
                      className="flex items-center gap-1.5 rounded px-2 py-1 font-medium text-[#00df8f] hover:bg-[#00df8f]/10">
                      <CalendarPlus className="h-3.5 w-3.5" /> Add batch
                    </button>
                  )}
                </div>
              </div>
            )
          )}
        </div>
      )}

      {showChanges && changes.length > 0 && (
        <div className="space-y-2 pt-2">
          <p className="flex items-center gap-1.5 font-semibold text-slate-300">
            <History className="h-3.5 w-3.5" /> Recent changes
          </p>
          <ul className="divide-y divide-[#102d38] rounded-lg border border-[#102d38]">
            {changes.slice(0, 15).map((c) => (
              <li key={c.id} className="flex flex-wrap items-start justify-between gap-2 px-3 py-2">
                <span className="min-w-0">
                  <span className="font-semibold text-slate-200">{c.course_name}</span>
                  <span className={c.fee_changed ? 'text-amber-300' : 'text-slate-400'}> · {c.summary}</span>
                </span>
                <span className="shrink-0 text-[11px] text-slate-500">
                  {c.actor === 'CLIENT' ? 'Client' : 'Team'}
                  {c.actor_name ? ` (${c.actor_name})` : ''}
                  {c.created_at ? ` · ${new Date(c.created_at.endsWith('Z') ? c.created_at : `${c.created_at}Z`).toLocaleString('en-IN')}` : ''}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};
