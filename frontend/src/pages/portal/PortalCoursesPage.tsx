import React from 'react';
import { Card } from '../../components/common/Card';
import { CourseCatalogue } from '../../components/courses/CourseCatalogue';
import { portalCoursesService } from '../../services/courses';

/** Coaching centres keep their courses and batches up to date; their AI employees quote only from here. */
export const PortalCoursesPage: React.FC = () => (
  <div className="mx-auto max-w-5xl space-y-4">
    <div>
      <h1 className="text-xl font-bold">Courses &amp; batches</h1>
      <p className="text-xs text-slate-400">Add a new course or batch, change timings, or mark a batch full.</p>
    </div>
    <Card>
      <CourseCatalogue api={portalCoursesService} />
    </Card>
  </div>
);
