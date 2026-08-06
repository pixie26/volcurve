package com.bnpparibas.cortex.datahub.client.example;

import java.time.LocalDate;
import java.util.List;

import com.fasterxml.jackson.annotation.JsonFormat;

public class DateListDto {
	
	public static final String YYYY_MM_DD = "yyyy-MM-dd";
	
	@JsonFormat(shape = JsonFormat.Shape.STRING, pattern = YYYY_MM_DD)
	private List<LocalDate> dates;

	public List<LocalDate> getDates() {
		return dates;
	}
}