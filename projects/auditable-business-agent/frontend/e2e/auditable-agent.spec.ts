import { expect, test, type Page } from "@playwright/test";

const customerServiceUsername = process.env.E2E_CUSTOMER_SERVICE_USERNAME ?? "e2e-agent";
const customerServicePassword = process.env.E2E_CUSTOMER_SERVICE_PASSWORD ?? "customer-service-password";
const approverUsername = process.env.E2E_APPROVER_USERNAME ?? "e2e-approver";
const approverPassword = process.env.E2E_APPROVER_PASSWORD ?? "approver-password-123";

async function login(page: Page, username: string, password: string) {
  await page.locator('input[name="username"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.locator(".message")).toContainText("登录成功");
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("tracking case completes without approval", async ({ page }) => {
  await login(page, customerServiceUsername, customerServicePassword);
  await page.locator('input[name="order_id"]').fill("ORD-101");
  await page.locator('select[name="request_type"]').selectOption("tracking");
  await page.locator('textarea[name="summary"]').fill("请查询物流状态。");
  await page.getByRole("button", { name: "提交案例" }).click();

  await expect(page.locator(".message")).toContainText("案例已完成，无需审批");
  await expect(page.getByText(/^状态：\s*completed$/)).toBeVisible();
  await expect(page.getByText(/^建议动作：\s*answer_only$/)).toBeVisible();
  await expect(page.getByText("knowledge_retrieved", { exact: true })).toBeVisible();
});

test("return case pauses and can be approved", async ({ page }) => {
  await login(page, customerServiceUsername, customerServicePassword);
  await page.locator('input[name="order_id"]').fill("ORD-100");
  await page.locator('select[name="request_type"]').selectOption("return");
  await page.locator('textarea[name="summary"]').fill("商品不适合，申请退货。");
  await page.getByRole("button", { name: "提交案例" }).click();

  await expect(page.locator(".message")).toContainText("案例已暂停，等待审批人操作");
  await expect(page.getByText(/^状态：\s*pending_approval$/)).toBeVisible();

  await login(page, approverUsername, approverPassword);
  await page.getByRole("button", { name: "以审批人身份批准" }).click();

  await expect(page.locator(".message")).toContainText("审批已通过，模拟工单已创建");
  await expect(page.getByText(/^状态：\s*completed$/)).toBeVisible();
  await expect(page.getByText("action_executed", { exact: true })).toBeVisible();
});
