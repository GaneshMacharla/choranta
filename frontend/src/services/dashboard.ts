import { request } from './api';
import { DashboardSummary } from '../types';

export const dashboardService = {
  getSummary: async (): Promise<DashboardSummary> => {
    return request<DashboardSummary>('/dashboard/summary');
  },
};
