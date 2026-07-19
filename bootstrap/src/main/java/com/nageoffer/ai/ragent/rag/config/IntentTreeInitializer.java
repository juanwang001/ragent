/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package com.nageoffer.ai.ragent.rag.config;

import com.nageoffer.ai.ragent.ingestion.service.IntentTreeService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

// 在应用完全启动后补齐首次运行必需的默认意图树。
@Slf4j
@Component
@RequiredArgsConstructor
public class IntentTreeInitializer implements ApplicationRunner {

    private final IntentTreeService intentTreeService;
    private final IntentTreeProperties intentTreeProperties;

    @Override
    public void run(ApplicationArguments args) {
        if (!intentTreeProperties.isInitializeOnEmpty()) {
            log.info("默认意图树自动初始化已关闭");
            return;
        }

        // 非空树完全由后台配置管理，启动过程不新增、更新或覆盖任何节点。
        if (!intentTreeService.getFullTree().isEmpty()) {
            log.info("意图树已存在，跳过默认意图树初始化");
            return;
        }

        int created = intentTreeService.initFromFactory();
        log.info("默认意图树初始化完成，新增 {} 个节点", created);
    }
}
