import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../services/api';
import { InventoryNumber, InventoryPage, OwnedNumber, numbersService } from '../../services/numbers';
import { InventoryPanel } from './InventoryPanel';
import { OwnedNumbersPanel } from './OwnedNumbersPanel';
import { PurchaseConfirmModal } from './PurchaseConfirmModal';

vi.mock('../../services/numbers', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/numbers')>();
  return {
    ...actual,
    numbersService: {
      inventory: vi.fn(), list: vi.fn(), purchase: vi.fn(), trunks: vi.fn().mockResolvedValue([]),
      assign: vi.fn(), unassign: vi.fn(), release: vi.fn(),
    },
  };
});

const api = numbersService as unknown as Record<string, ReturnType<typeof vi.fn>>;

const forSale = (overrides: Partial<InventoryNumber> = {}): InventoryNumber => ({
  e164: '+914071100000', country: 'IN', region: 'Telangana', number_type: 'Landline', number_type_derived: true,
  setup_fee: 100, monthly_fee: 300, currency: 'INR', available: true, is_mock: true, scenario: null, ...overrides,
});

const page = (items: InventoryNumber[]): InventoryPage => ({ items, page: 1, per_page: 25, total: items.length, mock_mode: true });

const owned = (overrides: Partial<OwnedNumber> = {}): OwnedNumber => ({
  id: 'pnm_1', provider: 'vobiz', provider_number_id: 'mock-1', e164: '+914071100000', country: 'IN', region: 'Telangana',
  number_type: 'Landline', number_type_derived: true, capabilities: { voice: true }, provider_status: 'active',
  internal_status: 'AVAILABLE', monthly_cost: 300, setup_cost: 100, currency: 'INR', application_id: 'mock_app', trunk_id: null, subaccount_auth_id: null,
  is_mock: true, attention: null, purchased_at: '2026-10-24T10:00:00Z', last_synced_at: null, released_at: null,
  created_at: '2026-10-24T10:00:00Z', next_billing_date: null, aadhaar_verification_required: false, assignment: null, ...overrides,
});

beforeEach(() => vi.clearAllMocks());

describe('InventoryPanel', () => {
  it('shows loading, then the numbers with their prices', async () => {
    let resolve!: (p: InventoryPage) => void;
    api.inventory.mockReturnValue(new Promise((r) => (resolve = r)));
    render(<InventoryPanel canBuy />);
    expect(screen.getByText('Loading numbers for sale...')).toBeInTheDocument();
    resolve(page([forSale(), forSale({ e164: '+918040000402', scenario: 'Simulates: insufficient Vobiz balance' })]));
    expect(await screen.findByText('+914071100000')).toBeInTheDocument();
    expect(screen.getAllByText('₹300')).toHaveLength(2);
    expect(screen.getByText('Simulates: insufficient Vobiz balance')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Buy' })).toHaveLength(2);
  });

  it('says so when nothing matches', async () => {
    api.inventory.mockResolvedValue(page([]));
    render(<InventoryPanel canBuy />);
    expect(await screen.findByText(/No numbers match/)).toBeInTheDocument();
  });

  it('shows the error and retries', async () => {
    api.inventory.mockRejectedValueOnce(new Error('Vobiz is unreachable')).mockResolvedValueOnce(page([forSale()]));
    render(<InventoryPanel canBuy />);
    expect(await screen.findByText('Vobiz is unreachable')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(await screen.findByText('+914071100000')).toBeInTheDocument();
    expect(api.inventory).toHaveBeenCalledTimes(2);
  });

  it('hides buying from people who may not buy', async () => {
    api.inventory.mockResolvedValue(page([forSale()]));
    render(<InventoryPanel canBuy={false} />);
    await screen.findByText('+914071100000');
    expect(screen.queryByRole('button', { name: 'Buy' })).not.toBeInTheDocument();
  });

  it('sends the filters to the search', async () => {
    api.inventory.mockResolvedValue(page([]));
    render(<InventoryPanel canBuy />);
    await screen.findByText(/No numbers match/);
    fireEvent.change(screen.getByLabelText('Number type'), { target: { value: 'TollFree' } });
    fireEvent.change(screen.getByLabelText('Number or prefix'), { target: { value: '1800' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() => expect(api.inventory).toHaveBeenLastCalledWith(expect.objectContaining({ number_type: 'TollFree', search: '1800', page: 1 })));
  });
});

describe('PurchaseConfirmModal', () => {
  it('needs confirming, shows the costs, and reuses one key when retried', async () => {
    const op = { id: 'nop_1', operation_type: 'PURCHASE', operation_status: 'SUCCEEDED', e164: '+914071100000' };
    api.purchase
      .mockRejectedValueOnce(new ApiError('Vobiz didn’t answer', 503, undefined, { code: 'provider_unreachable' }))
      .mockResolvedValueOnce({ operation: op, number: owned() });
    const onDone = vi.fn();
    render(<PurchaseConfirmModal number={forSale()} onClose={() => {}} onDone={onDone} />);

    expect(screen.getByText('₹400')).toBeInTheDocument(); // setup + first month
    expect(screen.getByText(/Mock mode: this purchase is simulated/)).toBeInTheDocument();
    const buy = screen.getByRole('button', { name: 'Buy number' });
    expect(buy).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(buy);
    expect(await screen.findByText('Vobiz didn’t answer')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Buy number' }));
    expect(await screen.findByText(/Bought\. It is now in the pool/)).toBeInTheDocument();
    const [first, second] = api.purchase.mock.calls.map((c) => c[0]);
    expect(second.idempotency_key).toBe(first.idempotency_key);
    expect(first).toMatchObject({ e164: '+914071100000', confirm: true, expected_monthly_cost: 300, expected_setup_cost: 100, currency: 'INR' });
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it('says plainly when the outcome is uncertain', async () => {
    api.purchase.mockResolvedValue({
      operation: { id: 'nop_2', operation_type: 'PURCHASE', operation_status: 'UNCERTAIN', error_message: 'No answer in time.' }, number: null,
    });
    render(<PurchaseConfirmModal number={forSale()} onClose={() => {}} onDone={() => {}} />);
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Buy number' }));
    expect(await screen.findByText(/No answer in time\..*won't be retried automatically/)).toBeInTheDocument();
  });
});

describe('OwnedNumbersPanel', () => {
  const renderPanel = () => render(<MemoryRouter><OwnedNumbersPanel isAdmin /></MemoryRouter>);

  it('lists numbers with who has them and what can be done', async () => {
    api.list.mockResolvedValue({
      items: [owned(), owned({ id: 'pnm_2', e164: '+918061100000', internal_status: 'ASSIGNED',
        assignment: { id: 'nas_1', client_id: 'cli_1', client_name: 'Smile Dental', agent_id: 'agt_1', agent_name: 'Priya', trunk_id: null,
          phone_number_id: 'phn_1', status: 'ACTIVE', assigned_by: 'ADMIN a@b.c', ended_by: null, end_reason: null,
          assigned_at: '2026-10-24T10:00:00Z', released_at: null } })],
      page: 1, per_page: 25, total: 2,
    });
    renderPanel();
    expect(await screen.findByText('Smile Dental')).toBeInTheDocument();
    expect(screen.getByText('Priya')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Assign' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Unassign' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Release' })).toBeInTheDocument();
  });

  it('has an empty state and an error state', async () => {
    api.list.mockResolvedValueOnce({ items: [], page: 1, per_page: 25, total: 0 });
    renderPanel();
    expect(await screen.findByText(/No numbers yet/)).toBeInTheDocument();
    api.list.mockRejectedValueOnce(new Error('Database unavailable'));
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }));
    expect(await screen.findByText('Database unavailable')).toBeInTheDocument();
  });
});
