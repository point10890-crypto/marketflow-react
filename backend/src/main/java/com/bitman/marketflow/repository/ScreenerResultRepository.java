package com.bitman.marketflow.repository;

import com.bitman.marketflow.entity.ScreenerResultEntity;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

public interface ScreenerResultRepository extends JpaRepository<ScreenerResultEntity, Long> {

    boolean existsByDate(LocalDate date);

    @Query("SELECT r.date FROM ScreenerResultEntity r WHERE r.filteredCount > 0 ORDER BY r.date DESC")
    List<LocalDate> findAllDatesWithSignals();

    @Query("SELECT r FROM ScreenerResultEntity r LEFT JOIN FETCH r.signals WHERE r.date = :date")
    Optional<ScreenerResultEntity> findByDate(LocalDate date);

    @Query("SELECT r FROM ScreenerResultEntity r LEFT JOIN FETCH r.signals WHERE r.date = (SELECT MAX(r2.date) FROM ScreenerResultEntity r2)")
    Optional<ScreenerResultEntity> findLatest();
}
