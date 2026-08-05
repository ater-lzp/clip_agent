<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAdminSession } from '../session'

const email=ref(''),password=ref(''),busy=ref(false),error=ref('')
const session=useAdminSession(),router=useRouter()
async function login():Promise<void>{busy.value=true;error.value='';try{await session.login(email.value,password.value);password.value='';await router.push('/')}catch(cause){error.value=cause instanceof Error?cause.message:'登录失败'}finally{busy.value=false}}
</script>
<template><section class="login-card"><p class="eyebrow">CLIP AGENT</p><h1>管理员控制台</h1><form @submit.prevent="login"><label>管理员邮箱<input v-model="email" type="email" required autocomplete="username" /></label><label>登录密码<input v-model="password" type="password" required autocomplete="current-password" /></label><button :disabled="busy">{{busy?'正在登录…':'安全登录'}}</button></form><p v-if="error" class="error" role="alert">{{error}}</p></section></template>
