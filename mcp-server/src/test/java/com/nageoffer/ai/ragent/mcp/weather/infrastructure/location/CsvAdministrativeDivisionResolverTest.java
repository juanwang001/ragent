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

package com.nageoffer.ai.ragent.mcp.weather.infrastructure.location;

import com.nageoffer.ai.ragent.mcp.weather.domain.model.AdministrativeLocationQuery;
import com.nageoffer.ai.ragent.mcp.weather.domain.model.GeoLocation;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class CsvAdministrativeDivisionResolverTest {

    private CsvAdministrativeDivisionResolver resolver;

    @BeforeEach
    void setUp() {
        resolver = new CsvAdministrativeDivisionResolver(
                new ClassPathResource("weather/china-mainland-divisions-wgs84.csv")
        );
    }

    @Test
    void shouldResolveOrdinaryProvinceCityCounty() {
        GeoLocation location = resolver.resolve(
                new AdministrativeLocationQuery("湖北省", "武汉市", "洪山区")
        );

        assertEquals("420111", location.adcode());
        assertEquals("湖北省武汉市洪山区", location.name());
        assertEquals(30.503023, location.latitude());
        assertEquals(114.337177, location.longitude());
    }

    @Test
    void shouldCompleteMunicipalityCityWhenCallerOmitsRepeatedLevel() {
        GeoLocation location = resolver.resolve(
                new AdministrativeLocationQuery("北京市", null, "朝阳区")
        );

        assertEquals("110105", location.adcode());
        assertEquals("北京市朝阳区", location.name());
    }

    @Test
    void shouldAcceptMunicipalityWithRepeatedCityAndShortAliases() {
        GeoLocation location = resolver.resolve(
                new AdministrativeLocationQuery("北京", "北京", "朝阳")
        );

        assertEquals("110105", location.adcode());
    }

    @Test
    void shouldResolveProvinceDirectCountyWithoutSyntheticCity() {
        GeoLocation location = resolver.resolve(
                new AdministrativeLocationQuery("河南省", null, "济源市")
        );

        assertEquals("419001", location.adcode());
        assertEquals("河南省济源市", location.name());
    }

    @Test
    void shouldResolvePrefectureCityWithoutSyntheticCounty() {
        GeoLocation location = resolver.resolve(
                new AdministrativeLocationQuery("广东省", "东莞市", null)
        );

        assertEquals("441900", location.adcode());
        assertEquals("广东省东莞市", location.name());
    }

    @Test
    void shouldRejectOrdinaryCountyWhenParentCityIsMissing() {
        IllegalArgumentException error = assertThrows(
                IllegalArgumentException.class,
                () -> resolver.resolve(
                        new AdministrativeLocationQuery("湖北省", null, "洪山区")
                )
        );

        assertTrue(error.getMessage().contains("城市"));
    }

    @Test
    void shouldRejectCityOutsideSelectedProvince() {
        IllegalArgumentException error = assertThrows(
                IllegalArgumentException.class,
                () -> resolver.resolve(
                        new AdministrativeLocationQuery("湖北省", "杭州市", null)
                )
        );

        assertTrue(error.getMessage().contains("杭州市"));
    }

    @Test
    void shouldKeepFullNamesAndRejectConflictingShortCountyAlias() {
        assertEquals(
                "130107",
                resolver.resolve(
                        new AdministrativeLocationQuery("河北省", "石家庄市", "井陉矿区")
                ).adcode()
        );
        assertEquals(
                "130121",
                resolver.resolve(
                        new AdministrativeLocationQuery("河北省", "石家庄市", "井陉县")
                ).adcode()
        );

        assertThrows(
                IllegalArgumentException.class,
                () -> resolver.resolve(
                        new AdministrativeLocationQuery("河北省", "石家庄市", "井陉")
                )
        );
    }
}
