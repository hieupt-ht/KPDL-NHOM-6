import { apiDateRange } from "./date-utils";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); this.name = "ApiError"; }
}

type Query = Record<string, string | number | undefined>;
type TransportOptions = { baseUrl: string; fetcher?: typeof fetch };

export function createApiTransport({ baseUrl, fetcher = fetch }: TransportOptions) {
  async function send(path: string, query: Query = {}, init?: RequestInit): Promise<Response> {
    const target = new URL(`/api/${path}`, baseUrl);
    for (const [key, value] of Object.entries(query)) if (value !== undefined && value !== "") target.searchParams.set(key, String(value));
    const headers = new Headers(init?.headers);
    const response = await fetcher(target.toString(), { ...init, headers, cache: "no-store" });
    if (!response.ok) {
      const message = response.status === 404 ? "Data Mart chưa có dữ liệu cho lựa chọn này." :
        response.status === 401 ? "API từ chối yêu cầu." :
        response.status === 403 ? "API không cho phép thao tác này." :
        response.status === 409 ? "Tác vụ đang chạy. Hãy kiểm tra trạng thái trước khi thử lại." :
        response.status === 504 ? "Chưa xác nhận được yêu cầu chạy. Kiểm tra trạng thái trước khi gửi lại." :
        response.status === 422 ? "Tham số lọc chưa phù hợp với hợp đồng API." :
        `Không tải được dữ liệu (HTTP ${response.status}).`;
      throw new ApiError(response.status, message);
    }
    return response;
  }

  async function request<T>(path: string, query?: Query, init?: RequestInit): Promise<T> {
    return (await send(path, query, init)).json() as Promise<T>;
  }

  async function list<T>(path: string, query: Query): Promise<T[]> {
    const result: T[] = [];
    let offset = 0;
    for (let page = 0; page < 100; page++) {
      const response = await send(path, { ...query, limit: 1000, offset });
      const rows: T[] = await response.json();
      if (!Array.isArray(rows)) throw new ApiError(502, "API trả cấu trúc danh sách không hợp lệ.");
      result.push(...rows);
      const header = response.headers.get("X-Total-Count");
      if (header === null) return result;
      const total = Number(header);
      if (!Number.isSafeInteger(total) || total < 0) throw new ApiError(502, "Thông tin phân trang không hợp lệ.");
      offset += rows.length;
      if (offset >= total) return result;
      if (!rows.length) throw new ApiError(409, "Dữ liệu đã thay đổi khi tải. Hãy thử lại.");
    }
    throw new ApiError(413, "Khoảng dữ liệu quá lớn. Hãy thu hẹp bộ lọc.");
  }

  return { request, list, range: apiDateRange };
}
