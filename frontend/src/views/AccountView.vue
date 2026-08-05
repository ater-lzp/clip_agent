<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { accountApi } from '../api'
import type { AccountData, LedgerEntry, MembershipPlan } from '../types/domain'

const data = ref<AccountData | null>(null)
const ledger = ref<LedgerEntry[]>([])
const loading = ref(true)
const submitting = ref(false)
const errorMessage = ref('')
const notice = ref('')
const cdk = ref('')
const accountPassword = ref('')
const paymentPassword = ref('')
const paymentConfirmation = ref('')
const purchasePassword = ref('')
const selectedPlan = ref<MembershipPlan | null>(null)
const paymentDialog = ref<HTMLElement | null>(null)
const money = (cents: number) => `¥${(cents / 100).toFixed(2)}`

async function load(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const [account, entries] = await Promise.all([accountApi.get(), accountApi.ledger()])
    data.value = account
    ledger.value = entries.items
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '账户信息加载失败'
  } finally { loading.value = false }
}

async function redeem(): Promise<void> {
  submitting.value = true; errorMessage.value = ''; notice.value = ''
  try {
    await accountApi.redeemCdk(cdk.value.trim()); cdk.value = ''; notice.value = 'CDK 充值成功'; await load()
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : 'CDK 充值失败' }
  finally { submitting.value = false }
}

async function savePaymentPassword(): Promise<void> {
  submitting.value = true; errorMessage.value = ''; notice.value = ''
  try {
    await accountApi.setPaymentPassword({ account_password: accountPassword.value, payment_password: paymentPassword.value, confirm_password: paymentConfirmation.value })
    accountPassword.value = ''; paymentPassword.value = ''; paymentConfirmation.value = ''
    notice.value = '支付密码已安全保存'; await load()
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '支付密码保存失败' }
  finally { submitting.value = false }
}

async function openPurchase(plan: MembershipPlan): Promise<void> {
  selectedPlan.value = plan
  purchasePassword.value = ''
  errorMessage.value = ''
  await nextTick()
  paymentDialog.value?.focus()
}

function closePurchase(): void {
  if (!submitting.value) selectedPlan.value = null
}

async function purchase(): Promise<void> {
  if (!selectedPlan.value) return
  const plan = selectedPlan.value
  submitting.value = true; errorMessage.value = ''; notice.value = ''
  try {
    await accountApi.purchase(plan.tier, purchasePassword.value, crypto.randomUUID())
    purchasePassword.value = ''; selectedPlan.value = null; notice.value = `${plan.name} 开通成功`; await load()
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '会员支付失败' }
  finally { submitting.value = false }
}

onMounted(load)
</script>

<template>
  <section class="page account-page">
    <div class="page-heading"><div><p class="eyebrow">账户中心</p><h1>余额与会员</h1></div><button class="secondary-button" type="button" :disabled="loading" @click="load">刷新</button></div>
    <div v-if="loading" class="state-card">正在加载账户信息…</div>
    <template v-else-if="data">
      <div class="account-stats">
        <article><span>账户余额</span><strong>{{ money(data.account.balance_cents) }}</strong></article>
        <article><span>当前会员</span><strong>{{ data.account.membership_tier.toUpperCase() }}</strong></article>
        <article><span>剩余生成次数</span><strong>{{ data.account.generations_remaining }}</strong></article>
        <article><span>已使用 / 总额度</span><strong>{{ data.account.generations_used }} / {{ data.account.generation_quota }}</strong></article>
      </div>
      <p v-if="notice" class="success-message" role="status">{{ notice }}</p><p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</p>
      <div class="account-grid">
        <article class="panel"><h2>CDK 充值</h2><p class="muted">余额只能通过管理员签发的一次性 CDK 充值。</p><form @submit.prevent="redeem"><label>充值 CDK<input v-model="cdk" required maxlength="24" placeholder="CLIP-XXXX-XXXX-XXXX-XXXX" autocomplete="off" /></label><button class="primary-button" type="submit" :disabled="submitting || cdk.length !== 24">立即充值</button></form></article>
        <article class="panel"><h2>{{ data.account.has_payment_password ? '修改支付密码' : '设置支付密码' }}</h2><p class="muted">首次购买会员前必须设置独立的 6 位数字支付密码。</p><form @submit.prevent="savePaymentPassword"><label>登录密码<input v-model="accountPassword" type="password" required autocomplete="current-password" /></label><label>支付密码<input v-model="paymentPassword" type="password" required pattern="\d{6}" maxlength="6" inputmode="numeric" autocomplete="new-password" /></label><label>确认支付密码<input v-model="paymentConfirmation" type="password" required pattern="\d{6}" maxlength="6" inputmode="numeric" autocomplete="new-password" /></label><button class="secondary-button" type="submit" :disabled="submitting">安全保存</button></form></article>
      </div>
      <section class="panel"><div class="section-heading"><div><p class="eyebrow">会员套餐</p><h2>增加创作额度</h2></div></div><div class="plan-grid"><article v-for="plan in data.plans" :key="plan.tier" class="plan-card"><span>{{ plan.name }}</span><strong>{{ money(plan.price_cents) }}</strong><p>有效期 {{ plan.duration_days }} 天 · 增加 {{ plan.generation_credits }} 次生成</p><button class="primary-button" :data-testid="`purchase-${plan.tier}`" type="button" :disabled="submitting" @click="openPurchase(plan)">立即购买</button></article></div></section>
      <section class="panel"><h2>余额流水</h2><div v-if="ledger.length === 0" class="empty-inline">暂无余额流水</div><div v-else class="ledger-list"><article v-for="entry in ledger" :key="entry.id"><div><strong>{{ entry.kind === 'cdk_recharge' ? 'CDK 充值' : '会员支付' }}</strong><small>{{ new Date(entry.created_at).toLocaleString('zh-CN') }}</small></div><span :class="entry.amount_cents > 0 ? 'credit' : 'debit'">{{ entry.amount_cents > 0 ? '+' : '' }}{{ money(entry.amount_cents) }}</span></article></div></section>
    </template>
    <div v-if="selectedPlan" class="modal-backdrop" @mousedown.self="closePurchase">
      <section ref="paymentDialog" class="modal-card payment-dialog" role="dialog" aria-modal="true" aria-labelledby="payment-title" tabindex="-1" @keydown.esc="closePurchase">
        <div class="section-heading"><div><p class="eyebrow">余额支付</p><h2 id="payment-title">确认购买 {{ selectedPlan.name }}</h2></div><button class="modal-close" type="button" :disabled="submitting" aria-label="关闭支付弹窗" @click="closePurchase">×</button></div>
        <dl class="payment-summary"><div><dt>套餐金额</dt><dd>{{ money(selectedPlan.price_cents) }}</dd></div><div><dt>账户余额</dt><dd>{{ data ? money(data.account.balance_cents) : '—' }}</dd></div><div><dt>增加额度</dt><dd>{{ selectedPlan.generation_credits }} 次</dd></div></dl>
        <form @submit.prevent="purchase"><label for="purchase-password">支付密码<input id="purchase-password" v-model="purchasePassword" type="password" required pattern="\d{6}" maxlength="6" inputmode="numeric" autocomplete="current-password" autofocus placeholder="请输入 6 位支付密码" /></label><p v-if="!data?.account.has_payment_password" class="field-error">当前账户尚未设置支付密码，请先关闭弹窗并完成设置。</p><p v-if="errorMessage" class="field-error" role="alert">{{ errorMessage }}</p><div class="modal-actions"><button class="secondary-button" type="button" :disabled="submitting" @click="closePurchase">取消</button><button class="primary-button" data-testid="confirm-purchase" type="submit" :disabled="submitting || purchasePassword.length !== 6 || !data?.account.has_payment_password">{{ submitting ? '正在支付…' : `支付 ${money(selectedPlan.price_cents)}` }}</button></div></form>
      </section>
    </div>
  </section>
</template>
